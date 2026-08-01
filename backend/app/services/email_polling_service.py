"""Scheduled Gmail polling.

The entry point that keeps the local mailbox mirror (see
``app/services/email_ingestion_service.py``) current without a Gmail
push-notification webhook. For each user with a stored Google credential:
refresh the access token, search Gmail for messages received since the last
poll (bounded to a recent window on the very first poll, to avoid importing
a mailbox's entire history), and ingest every message found.

Fault tolerance:

* One user's token-refresh or search failure is logged and skipped -- it
  does not abort polling for the other users in the same sweep.
* One message's ingestion failure is pushed to the retry queue (see
  ``app/services/retry_queue.py``) rather than aborting the rest of that
  user's poll.
* The per-user "last polled" watermark only advances once every matching
  message has actually been fetched (i.e. pagination fully drained). If a
  backlog is larger than one poll can process, the watermark stays put and
  the next scheduled run picks up exactly where this one left off --
  ingestion is idempotent (see ``EmailIngestionService.ingest_message``), so
  re-querying the same window on the next run is always safe, never lossy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.config.logging import get_logger
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.gmail_client import GmailClient
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.google_credential import GoogleCredential
from app.infra.models.user import User
from app.infra.queue import AIProcessingQueue
from app.infra.repositories.attachment import AttachmentRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.email_ingestion_service import EmailIngestionService
from app.services.google_auth_service import GoogleAuthService
from app.services.retry_queue import RetryQueueService

logger = get_logger(__name__)

_INITIAL_POLL_WINDOW = timedelta(hours=24)
_MESSAGES_PER_PAGE = 50
_MAX_MESSAGES_PER_POLL = 200


async def poll_all_users(
    database: Database,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    rate_limiter: TokenBucketRateLimiter,
    event_bus: EventBus,
    ai_queue: AIProcessingQueue,
) -> int:
    """Poll Gmail for every user with a stored credential.

    Entry point for the periodic APScheduler email-polling job (see
    ``app/scheduler.py``).

    Returns:
        The total number of messages successfully processed (new or
        already-ingested) across all users.
    """
    async with database.session() as session:
        credential_repo = GoogleCredentialRepository(session)
        credentials = await credential_repo.list(limit=10_000)
        if not credentials:
            return 0

        user_repo = UserRepository(session)
        auth_service = GoogleAuthService(
            settings=settings,
            oauth_client=GoogleOAuthClient(http_client, settings.oauth),
            cipher=TokenCipher(settings.security.token_encryption_key),
            user_repo=user_repo,
            tenant_repo=TenantRepository(session),
            credential_repo=credential_repo,
            session_repo=SessionRepository(session),
            db_session=session,
        )
        email_repo = EmailRepository(session)
        attachment_repo = AttachmentRepository(session)
        retry_queue = RetryQueueService(FailedJobRepository(session))

        total_processed = 0
        for credential in credentials:
            user = await user_repo.get(credential.user_id)
            if user is None:
                continue
            try:
                access_token = await auth_service.get_valid_access_token(user)
            except Exception as exc:
                logger.warning(
                    "email_poll_token_refresh_failed",
                    user_id=str(user.id),
                    error=str(exc),
                )
                continue

            gmail_client = GmailClient(
                http_client, settings.gmail, access_token, rate_limiter
            )
            ingestion_service = EmailIngestionService(
                gmail_client=gmail_client,
                email_repo=email_repo,
                attachment_repo=attachment_repo,
                event_bus=event_bus,
                ai_queue=ai_queue,
                db_session=session,
            )
            total_processed += await _poll_user(
                user=user,
                credential=credential,
                gmail_client=gmail_client,
                ingestion_service=ingestion_service,
                credential_repo=credential_repo,
                retry_queue=retry_queue,
            )
        return total_processed


async def _poll_user(
    *,
    user: User,
    credential: GoogleCredential,
    gmail_client: GmailClient,
    ingestion_service: EmailIngestionService,
    credential_repo: GoogleCredentialRepository,
    retry_queue: RetryQueueService,
) -> int:
    poll_started_at = datetime.now(UTC)
    since = credential.last_polled_at or (poll_started_at - _INITIAL_POLL_WINDOW)
    query = f"after:{int(since.timestamp())}"

    processed = 0
    page_token: str | None = None
    fully_drained = True

    while True:
        try:
            page = await gmail_client.search_messages(
                query=query, page_token=page_token, max_results=_MESSAGES_PER_PAGE
            )
        except Exception as exc:
            logger.warning(
                "email_poll_search_failed", user_id=str(user.id), error=str(exc)
            )
            fully_drained = False
            break

        for message in page.messages:
            try:
                await ingestion_service.ingest_message(user, message.id)
                processed += 1
            except Exception as exc:
                logger.warning(
                    "email_poll_ingest_failed",
                    user_id=str(user.id),
                    message_id=message.id,
                    error=str(exc),
                )
                await retry_queue.enqueue_failure(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    job_type="email_ingestion",
                    payload={"user_id": str(user.id), "message_id": message.id},
                    error=exc,
                )

        if page.next_page_token is None:
            break
        if processed >= _MAX_MESSAGES_PER_POLL:
            fully_drained = False
            break
        page_token = page.next_page_token

    if fully_drained:
        await credential_repo.update_fields(
            credential.id, last_polled_at=poll_started_at
        )

    return processed
