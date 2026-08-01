"""Integration tests for morning/weekly digest generation.

Drives :class:`DigestService` against a real (SQLite-backed) database --
deterministic, template-based content, so no fake LLM server is needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.summary import SummaryRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.dashboard import DashboardService
from app.services.digest_service import DigestService


async def _seed_user(database: Database) -> User:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        return await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
                display_name="Jamie Rivera",
            )
        )


def _build_digest_service(session) -> DigestService:
    dashboard_service = DashboardService(
        EmailRepository(session),
        TaskRepository(session),
        NotificationRepository(session),
        DraftReplyRepository(session),
    )
    return DigestService(
        dashboard_service,
        EmailRepository(session),
        TaskRepository(session),
        SummaryRepository(session),
        NotificationRepository(session),
    )


@pytest.mark.asyncio
async def test_morning_digest_stores_summary_and_notification(
    database: Database,
) -> None:
    user = await _seed_user(database)

    async with database.session() as session:
        await EmailRepository(session).add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="msg-1",
                gmail_thread_id="thread-1",
                subject="Contract needs your signature",
                from_address="client@example.com",
                received_at=datetime.now(UTC),
                category="action_required",
                priority_score=0.9,
                has_deadline=True,
                deadline_at=datetime.now(UTC) + timedelta(hours=6),
            )
        )

    async with database.session() as session:
        digest_service = _build_digest_service(session)
        summary = await digest_service.build_morning_digest(user, user.tenant_id)

    assert summary.summary_type == "daily_digest"
    assert "Jamie" in summary.content
    assert "Contract needs your signature" in summary.content

    async with database.session() as session:
        stored = await SummaryRepository(session).get(summary.id)
        assert stored is not None

        notifications = await NotificationRepository(session).list_by_user(user.id)
        assert any(n.type == "morning_digest" for n in notifications)


@pytest.mark.asyncio
async def test_weekly_digest_reports_this_weeks_activity(database: Database) -> None:
    user = await _seed_user(database)

    async with database.session() as session:
        digest_service = _build_digest_service(session)
        summary = await digest_service.build_weekly_digest(user, user.tenant_id)

    assert summary.summary_type == "weekly_digest"
    assert "Weekly recap" in summary.content

    async with database.session() as session:
        notifications = await NotificationRepository(session).list_by_user(user.id)
        assert any(n.type == "weekly_digest" for n in notifications)
