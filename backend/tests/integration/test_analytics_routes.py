"""Integration tests for the ``/api/v1/analytics/*`` endpoints."""

from __future__ import annotations

import pytest
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


@pytest.mark.asyncio
async def test_daily_emails_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/analytics/daily-emails")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_daily_emails_returns_zero_filled_series(
    logged_in_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        await EmailRepository(session).add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="msg-1",
                gmail_thread_id="thread-1",
                subject="Hi",
                from_address="a@example.com",
                received_at=utcnow(),
            )
        )

    response = await logged_in_client.get(
        "/api/v1/analytics/daily-emails", params={"days": 5}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 6
    assert sum(point["count"] for point in body) == 1


@pytest.mark.asyncio
async def test_daily_emails_rejects_range_beyond_cap(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.get(
        "/api/v1/analytics/daily-emails", params={"days": 401}
    )
    assert response.status_code == 422  # FastAPI's own Query(le=400) bound


@pytest.mark.asyncio
async def test_unread_summary_returns_current_snapshot(
    logged_in_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        await EmailRepository(session).add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="msg-unread",
                gmail_thread_id="thread-unread",
                subject="Unread",
                from_address="a@example.com",
                received_at=utcnow(),
                is_read=False,
                category="fyi",
            )
        )

    response = await logged_in_client.get("/api/v1/analytics/unread-summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_unread"] >= 1
    assert any(row["category"] == "fyi" for row in body["by_category"])


@pytest.mark.asyncio
async def test_full_report_returns_every_section(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get(
        "/api/v1/analytics/report", params={"days": 14}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["range_days"] == 14
    for key in (
        "daily_email_volume",
        "weekly_email_volume",
        "monthly_trends",
        "category_distribution",
        "priority_distribution",
        "response_time",
        "unread_summary",
        "task_completion",
    ):
        assert key in body


@pytest.mark.asyncio
async def test_export_csv_downloads_a_csv_file(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get(
        "/api/v1/analytics/export.csv", params={"days": 7}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "Daily Email Volume" in response.text


@pytest.mark.asyncio
async def test_export_pdf_downloads_a_pdf_file(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get(
        "/api/v1/analytics/export.pdf", params={"days": 7}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_category_distribution_isolated_per_user(
    logged_in_client: AsyncClient, database: Database
) -> None:
    """Emails from a different tenant must never appear in this user's report."""
    async with database.session() as session:
        other_tenant = await TenantRepository(session).add(
            Tenant(name="Other Co", slug="other-co-analytics")
        )
        other_user = await UserRepository(session).add(
            User(
                tenant_id=other_tenant.id,
                google_subject="other-sub",
                email="other@example.com",
            )
        )
        await EmailRepository(session).add(
            Email(
                tenant_id=other_tenant.id,
                user_id=other_user.id,
                gmail_message_id="other-msg",
                gmail_thread_id="other-thread",
                subject="Not yours",
                from_address="x@example.com",
                received_at=utcnow(),
                category="spam",
            )
        )

    response = await logged_in_client.get(
        "/api/v1/analytics/category-distribution", params={"days": 30}
    )
    assert response.status_code == 200
    categories = [row["category"] for row in response.json()]
    assert "spam" not in categories
