"""Integration tests for Google Calendar synchronization.

Drives :func:`~app.services.calendar_sync_service.sync_all_users` against a
real (SQLite-backed) database and the fake Google server's calendar
endpoints (see ``tests/fake_google/app.py``) -- a real OAuth login round
trip creates the credential, then real HTTP calls push events.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.infra.db.session import Database
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.calendar_sync_service import sync_all_users
from app.services.google_auth_service import GoogleAuthService
from httpx import AsyncClient

from tests.fake_google.app import VALID_AUTH_CODE, FakeGoogleState


async def _login(
    database: Database, settings: Settings, http_client: AsyncClient
) -> User:
    async with database.session() as session:
        auth_service = GoogleAuthService(
            settings=settings,
            oauth_client=GoogleOAuthClient(http_client, settings.oauth),
            cipher=TokenCipher(settings.security.token_encryption_key),
            user_repo=UserRepository(session),
            tenant_repo=TenantRepository(session),
            credential_repo=GoogleCredentialRepository(session),
            session_repo=SessionRepository(session),
            db_session=session,
        )
        return await auth_service.complete_login(code=VALID_AUTH_CODE)


def _rate_limiter() -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(rate_per_second=1000.0, burst_capacity=1000)


@pytest.mark.asyncio
async def test_sync_creates_new_event_on_google_calendar(
    database: Database,
    settings: Settings,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
) -> None:
    user = await _login(database, settings, fake_google_http_client)

    async with database.session() as session:
        event = await CalendarEventRepository(session).add(
            CalendarEvent(
                tenant_id=user.tenant_id,
                user_id=user.id,
                title="Quarterly review",
                location="Conference Room A",
                start_at=datetime(2026, 8, 5, 14, 0),
                end_at=datetime(2026, 8, 5, 15, 0),
                status="tentative",
            )
        )
        event_id = event.id

    synced = await sync_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=_rate_limiter(),
    )
    assert synced == 1
    assert len(fake_google_state.calendar_events) == 1
    remote_event = next(iter(fake_google_state.calendar_events.values()))
    assert remote_event["summary"] == "Quarterly review"

    async with database.session() as session:
        refreshed = await CalendarEventRepository(session).get(event_id)
        assert refreshed is not None
        assert refreshed.google_event_id is not None
        assert refreshed.last_synced_at is not None


@pytest.mark.asyncio
async def test_sync_is_idempotent_until_event_changes(
    database: Database,
    settings: Settings,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
) -> None:
    user = await _login(database, settings, fake_google_http_client)

    async with database.session() as session:
        event = await CalendarEventRepository(session).add(
            CalendarEvent(
                tenant_id=user.tenant_id,
                user_id=user.id,
                title="Kickoff",
                start_at=datetime(2026, 8, 5, 14, 0),
                end_at=datetime(2026, 8, 5, 15, 0),
                status="tentative",
            )
        )
        event_id = event.id

    rate_limiter = _rate_limiter()
    first_sync = await sync_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=rate_limiter,
    )
    assert first_sync == 1

    # Nothing changed locally -- a second sync pass should push nothing new.
    second_sync = await sync_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=rate_limiter,
    )
    assert second_sync == 0
    assert len(fake_google_state.calendar_events) == 1

    # Edit the event -- it becomes eligible for re-sync (an update, not a
    # second create), and Google Calendar's copy reflects the new title.
    async with database.session() as session:
        await CalendarEventRepository(session).update_fields(
            event_id, title="Kickoff (rescheduled)"
        )

    third_sync = await sync_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=rate_limiter,
    )
    assert third_sync == 1
    assert len(fake_google_state.calendar_events) == 1
    remote_event = next(iter(fake_google_state.calendar_events.values()))
    assert remote_event["summary"] == "Kickoff (rescheduled)"


@pytest.mark.asyncio
async def test_sync_skips_users_without_credentials(
    database: Database,
    settings: Settings,
    fake_google_http_client: AsyncClient,
) -> None:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            )
        )

    synced = await sync_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=_rate_limiter(),
    )
    assert synced == 0
