"""Integration tests proving the dashboard/analytics cache is actually applied."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


async def _add_email(database: Database, tenant_id: object, user_id: object) -> None:
    async with database.session() as session:
        await EmailRepository(session).add(
            Email(
                tenant_id=tenant_id,
                user_id=user_id,
                gmail_message_id=f"msg-{datetime.now(UTC).timestamp()}",
                gmail_thread_id="thread-1",
                subject="Hi",
                from_address="a@example.com",
                received_at=utcnow(),
            )
        )


@pytest.mark.asyncio
async def test_dashboard_summary_serves_a_cached_value_within_ttl(
    logged_in_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        tenant_id, user_id = user.tenant_id, user.id

    await _add_email(database, tenant_id, user_id)
    first = await logged_in_client.get("/api/v1/dashboard/summary")
    assert first.status_code == 200
    assert first.json()["total_emails"] == 1

    # A second email lands directly in the DB, bypassing the endpoint --
    # a fresh (uncached) call would see 2.
    await _add_email(database, tenant_id, user_id)
    second = await logged_in_client.get("/api/v1/dashboard/summary")
    assert second.status_code == 200
    assert second.json()["total_emails"] == 1  # still the cached value


@pytest.mark.asyncio
async def test_analytics_category_distribution_is_cached_per_param_set(
    logged_in_client: AsyncClient,
) -> None:
    # Different `days` values must not collide on the same cache key.
    a = await logged_in_client.get(
        "/api/v1/analytics/category-distribution", params={"days": 30}
    )
    b = await logged_in_client.get(
        "/api/v1/analytics/category-distribution", params={"days": 90}
    )
    assert a.status_code == 200
    assert b.status_code == 200
