"""Integration tests for the scheduled Gmail-polling service.

Drives :func:`poll_all_users` against a real (SQLite-backed) database and
the fake Gmail server, using a real Google credential produced by an actual
OAuth login round-trip (``logged_in_client``) rather than a hand-inserted
row -- the encrypted tokens it stores must be genuinely decryptable by
:class:`GoogleAuthService` for polling to work at all.
"""

from __future__ import annotations

import pytest
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.queue import AIProcessingQueue
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.user import UserRepository
from app.services.email_polling_service import poll_all_users
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


@pytest.mark.asyncio
async def test_poll_all_users_ingests_every_fake_message(
    logged_in_client: AsyncClient,
    database: Database,
    fake_google_http_client: AsyncClient,
    settings: Settings,
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        user_id = user.id

    processed = await poll_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=TokenBucketRateLimiter(
            rate_per_second=1000.0, burst_capacity=1000
        ),
        event_bus=EventBus(),
        ai_queue=AIProcessingQueue(),
    )
    # The fake Gmail server always returns its two fixture messages
    # (msg-1, msg-2) regardless of the `after:` query polling sends.
    assert processed == 2

    async with database.session() as session:
        total_emails = await EmailRepository(session).count_total(user_id)
        assert total_emails == 2

        credential = (await GoogleCredentialRepository(session).list(limit=10))[0]
        assert credential.last_polled_at is not None


@pytest.mark.asyncio
async def test_poll_all_users_is_idempotent_across_runs(
    logged_in_client: AsyncClient,
    database: Database,
    fake_google_http_client: AsyncClient,
    settings: Settings,
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        user_id = user.id

    kwargs: dict[str, object] = {
        "http_client": fake_google_http_client,
        "rate_limiter": TokenBucketRateLimiter(
            rate_per_second=1000.0, burst_capacity=1000
        ),
        "event_bus": EventBus(),
        "ai_queue": AIProcessingQueue(),
    }
    await poll_all_users(database, settings, **kwargs)
    await poll_all_users(database, settings, **kwargs)

    async with database.session() as session:
        total_emails = await EmailRepository(session).count_total(user_id)
        assert total_emails == 2  # no duplicates on the second poll


@pytest.mark.asyncio
async def test_poll_all_users_with_no_credentials_is_a_noop(
    database: Database,
    fake_google_http_client: AsyncClient,
    settings: Settings,
) -> None:
    processed = await poll_all_users(
        database,
        settings,
        http_client=fake_google_http_client,
        rate_limiter=TokenBucketRateLimiter(
            rate_per_second=1000.0, burst_capacity=1000
        ),
        event_bus=EventBus(),
        ai_queue=AIProcessingQueue(),
    )
    assert processed == 0
