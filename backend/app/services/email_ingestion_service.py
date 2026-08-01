"""Email ingestion pipeline.

Implements the full Phase 4 pipeline for one Gmail message:

    Read Gmail -> Download -> Parse HTML -> Extract plain text ->
    Extract metadata -> Extract sender -> Extract attachments ->
    Store in the database -> Publish event -> Queue AI processing

Downloading and MIME parsing (splitting headers/text-plain/text-html/
attachment metadata) already happen inside
:meth:`~app.infra.google.gmail_client.GmailClient.get_message`; this service
adds the BeautifulSoup plain-text fallback, persistence, duplicate
detection, retrying, and downstream event/queue publication.
"""

from __future__ import annotations

import email.utils
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.logging import get_logger
from app.infra.events import EmailIngestedEvent, EventBus
from app.infra.google.gmail_client import GmailClient
from app.infra.google.html_text import html_to_text
from app.infra.metrics import EMAILS_INGESTED_TOTAL
from app.infra.models.attachment import Attachment
from app.infra.models.email import Email
from app.infra.models.user import User
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.infra.repositories.attachment import AttachmentRepository
from app.infra.repositories.email import EmailRepository

logger = get_logger(__name__)

# Network hiccups and DB connectivity blips only. IntegrityError (a
# duplicate-message race) is handled explicitly, not retried -- retrying it
# would just deterministically fail again.
_TRANSIENT_EXCEPTIONS = (OperationalError, ConnectionError, TimeoutError)


def _parse_received_at(date_header: str) -> datetime:
    """Parse an RFC 2822 ``Date`` header into a naive UTC datetime.

    Falls back to "now" for a missing or unparseable header rather than
    failing ingestion over a malformed date -- the rest of the codebase
    stores naive-but-UTC-by-convention timestamps (see
    ``app/infra/db/mixins.py``), so any timezone offset is normalized away.
    """
    if not date_header:
        return datetime.now(UTC).replace(tzinfo=None)
    try:
        parsed = email.utils.parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError):
        return datetime.now(UTC).replace(tzinfo=None)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


class EmailIngestionService:
    """Ingests Gmail messages into local storage, one message at a time.

    Args:
        gmail_client: Authenticated Gmail client for the target mailbox.
        email_repo: Repository for the ``emails`` table.
        attachment_repo: Repository for the ``attachments`` table.
        event_bus: Bus to publish :class:`EmailIngestedEvent` on.
        ai_queue: Queue to enqueue a follow-up AI-processing job on.
        db_session: The request/job-scoped session, used to roll back after
            a caught duplicate-insert race (see :meth:`_ingest_once`).
        max_attempts: Retry attempts for transient (network/DB) failures.
    """

    def __init__(
        self,
        *,
        gmail_client: GmailClient,
        email_repo: EmailRepository,
        attachment_repo: AttachmentRepository,
        event_bus: EventBus,
        ai_queue: AIProcessingQueue,
        db_session: AsyncSession,
        max_attempts: int = 3,
    ) -> None:
        self._gmail = gmail_client
        self._emails = email_repo
        self._attachments = attachment_repo
        self._event_bus = event_bus
        self._ai_queue = ai_queue
        self._db_session = db_session
        self._max_attempts = max_attempts

    async def ingest_message(self, user: User, message_id: str) -> Email:
        """Run the full ingestion pipeline for one Gmail message.

        Idempotent: if this message was already ingested for this user, the
        existing row is returned and no new event/job is published --
        re-running ingestion (e.g. after a crash or an at-least-once
        delivery from a future push-notification handler) is always safe.
        """
        # Captured once, up front: a caught IntegrityError later triggers a
        # rollback, which (by default) expires every ORM object loaded in
        # this session, including `user`. Async SQLAlchemy cannot transparently
        # re-fetch an expired attribute on access (it raises MissingGreenlet),
        # so `user.id`/`user.tenant_id` must not be touched again after that
        # point -- these plain values are used everywhere instead.
        user_id, tenant_id = user.id, user.tenant_id

        existing = await self._emails.get_by_gmail_message_id(user_id, message_id)
        if existing is not None:
            logger.info(
                "email_ingestion_skipped_duplicate",
                user_id=str(user_id),
                gmail_message_id=message_id,
            )
            return existing

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=0.5, max=10.0),
            reraise=True,
        ):
            with attempt:
                return await self._ingest_once(user_id, tenant_id, message_id)

        # pragma: no cover -- AsyncRetrying always returns or raises above.
        raise AssertionError("unreachable")

    async def _ingest_once(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, message_id: str
    ) -> Email:
        parsed = await self._gmail.get_message(message_id)

        text_plain = parsed.text_plain
        if text_plain is None and parsed.text_html:
            text_plain = html_to_text(parsed.text_html)

        try:
            email_row = await self._emails.add(
                Email(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    gmail_message_id=parsed.id,
                    gmail_thread_id=parsed.thread_id,
                    subject=parsed.subject,
                    snippet=parsed.snippet,
                    from_address=parsed.from_address,
                    to_addresses=parsed.to_address,
                    cc_addresses=parsed.cc_address,
                    body_text=text_plain,
                    body_html=parsed.text_html,
                    received_at=_parse_received_at(parsed.date),
                )
            )
        except IntegrityError:
            # Lost a race with a concurrent ingestion of the same message
            # (e.g. two workers picking up the same job). The failed flush
            # leaves the transaction unusable until rolled back.
            await self._db_session.rollback()
            existing = await self._emails.get_by_gmail_message_id(user_id, parsed.id)
            if existing is None:
                raise  # a different constraint failed; do not swallow it
            logger.info(
                "email_ingestion_lost_duplicate_race",
                user_id=str(user_id),
                gmail_message_id=parsed.id,
            )
            return existing

        for meta in parsed.attachments:
            await self._attachments.add(
                Attachment(
                    tenant_id=tenant_id,
                    email_id=email_row.id,
                    gmail_attachment_id=meta.attachment_id,
                    filename=meta.filename,
                    mime_type=meta.mime_type,
                    size_bytes=meta.size,
                )
            )

        await self._publish_and_enqueue(user_id, tenant_id, email_row)

        EMAILS_INGESTED_TOTAL.inc()
        logger.info(
            "email_ingested",
            user_id=str(user_id),
            email_id=str(email_row.id),
            gmail_message_id=email_row.gmail_message_id,
            attachment_count=len(parsed.attachments),
        )
        return email_row

    async def _publish_and_enqueue(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, email_row: Email
    ) -> None:
        event = EmailIngestedEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            email_id=email_row.id,
            gmail_message_id=email_row.gmail_message_id,
        )
        await self._event_bus.publish(event)
        await self._ai_queue.enqueue(
            AIProcessingJob(
                tenant_id=tenant_id,
                user_id=user_id,
                email_id=email_row.id,
                gmail_message_id=email_row.gmail_message_id,
            )
        )
