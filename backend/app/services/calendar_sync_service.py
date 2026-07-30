"""Google Calendar synchronization.

Pushes locally-created or AI-suggested calendar events (see
``app/agents/graph.py``'s ``calendar_suggestion``/``database_update`` nodes)
to each user's primary Google Calendar. This is a one-directional push, not
a full bidirectional sync: it creates/updates the Google Calendar event
that corresponds to a ``CalendarEvent`` row, but does not pull independent
changes made directly in Google Calendar back into this database. That is
a deliberate scope choice -- every event this system creates originates
here, so "synchronize" means keeping Google Calendar's copy current with
ours, not reconciling two independently-editable sources of truth.

:func:`sync_all_users` is the entry point the periodic APScheduler job (see
``app/scheduler.py``) calls; :class:`CalendarSyncService` does the actual
per-user push and is also usable directly (e.g. from a future "sync now"
API route) without going through the scheduler.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import httpx

from app.config.logging import get_logger
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.infra.db.session import Database
from app.infra.google.calendar_client import GoogleCalendarClient
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.calendar_event import CalendarEvent
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


def _content_hash(event: CalendarEvent) -> str:
    """Hash the fields Google Calendar actually needs to know about.

    Used to detect whether an event needs re-syncing. Deliberately not a
    timestamp comparison against ``updated_at`` (a server-side
    ``onupdate=func.now()`` column) -- that column's precision (whole
    seconds, on SQLite) isn't fine enough to reliably order against a
    Python-side sync timestamp when both happen within the same second, and
    a content hash sidesteps clock precision entirely.
    """
    payload = "|".join(
        (
            event.title,
            event.description or "",
            event.location or "",
            event.start_at.isoformat(),
            event.end_at.isoformat(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CalendarSyncService:
    """Pushes one user's pending ``CalendarEvent`` rows to Google Calendar."""

    def __init__(
        self,
        repository: CalendarEventRepository,
        calendar_client: GoogleCalendarClient,
    ) -> None:
        self._repo = repository
        self._calendar_client = calendar_client

    async def sync_user(self, user_id: uuid.UUID) -> int:
        """Push every event needing sync for one user.

        A single event's failure (e.g. the user deleted it directly in
        Google Calendar and it 404s on update) is logged and skipped rather
        than aborting the rest of that user's sync.

        Returns:
            The number of events successfully pushed.
        """
        events = await self._repo.list_active(user_id)
        synced = 0
        for event in events:
            current_hash = _content_hash(event)
            if event.google_event_id is not None and event.synced_hash == current_hash:
                continue
            try:
                await self._sync_one(event, current_hash)
                synced += 1
            except Exception as exc:
                logger.warning(
                    "calendar_event_sync_failed",
                    event_id=str(event.id),
                    error=str(exc),
                )
        return synced

    async def _sync_one(self, event: CalendarEvent, content_hash: str) -> None:
        if event.google_event_id is None:
            remote = await self._calendar_client.create_event(
                title=event.title,
                description=event.description or "",
                location=event.location or "",
                start_at=event.start_at,
                end_at=event.end_at,
            )
            google_event_id = remote.id
        else:
            await self._calendar_client.update_event(
                event.google_event_id,
                title=event.title,
                description=event.description or "",
                location=event.location or "",
                start_at=event.start_at,
                end_at=event.end_at,
            )
            google_event_id = event.google_event_id

        await self._repo.update_fields(
            event.id,
            google_event_id=google_event_id,
            last_synced_at=datetime.now(UTC),
            synced_hash=content_hash,
        )


async def sync_all_users(
    database: Database,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    rate_limiter: TokenBucketRateLimiter,
) -> int:
    """Sync every user with a stored Google credential.

    Entry point for the periodic APScheduler calendar-sync job. Skips any
    individual user whose access token can't be refreshed (e.g. they
    revoked access, or the app's OAuth client isn't configured) rather than
    failing the whole run -- a user's existing token may still be valid and
    not need a refresh at all, so this deliberately does not gate on
    ``settings.oauth.is_configured`` up front.

    Returns:
        The total number of events pushed across all users.
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
        calendar_event_repo = CalendarEventRepository(session)

        total_synced = 0
        for credential in credentials:
            user = await user_repo.get(credential.user_id)
            if user is None:
                continue
            try:
                access_token = await auth_service.get_valid_access_token(user)
            except Exception as exc:
                logger.warning(
                    "calendar_sync_token_refresh_failed",
                    user_id=str(user.id),
                    error=str(exc),
                )
                continue

            calendar_client = GoogleCalendarClient(
                http_client, settings.calendar, access_token, rate_limiter
            )
            sync_service = CalendarSyncService(calendar_event_repo, calendar_client)
            total_synced += await sync_service.sync_user(user.id)

        return total_synced
