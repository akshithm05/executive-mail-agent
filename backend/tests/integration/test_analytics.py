"""Integration tests for :class:`AnalyticsService`'s aggregation logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.models.draft_reply import DraftReply
from app.infra.models.email import Email
from app.infra.models.task import Task
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.analytics import AnalyticsService


async def _seed_user(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        user = await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
        return tenant.id, user.id


async def _add_email(
    database: Database,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    received_at: datetime,
    category: str | None = None,
    priority_score: float | None = None,
    is_read: bool = True,
) -> Email:
    async with database.session() as session:
        return await EmailRepository(session).add(
            Email(
                tenant_id=tenant_id,
                user_id=user_id,
                gmail_message_id=f"msg-{uuid.uuid4().hex[:8]}",
                gmail_thread_id=f"thread-{uuid.uuid4().hex[:8]}",
                subject="Subject",
                from_address="sender@example.com",
                received_at=received_at,
                category=category,
                priority_score=priority_score,
                is_read=is_read,
            )
        )


def _service(session: object) -> AnalyticsService:
    return AnalyticsService(
        EmailRepository(session),  # type: ignore[arg-type]
        TaskRepository(session),  # type: ignore[arg-type]
        DraftReplyRepository(session),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_daily_email_volume_zero_fills_empty_days(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(database, tenant_id, user_id, received_at=now)
    await _add_email(database, tenant_id, user_id, received_at=now)
    await _add_email(database, tenant_id, user_id, received_at=now - timedelta(days=2))

    async with database.session() as session:
        points = await _service(session).daily_email_volume(user_id, days=5)

    by_date = {p.period: p.count for p in points}
    assert len(points) == 6  # inclusive of both endpoints
    assert by_date[now.date()] == 2
    assert by_date[(now - timedelta(days=2)).date()] == 1
    assert by_date[(now - timedelta(days=1)).date()] == 0


@pytest.mark.asyncio
async def test_weekly_email_volume_buckets_by_week(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(database, tenant_id, user_id, received_at=now)
    await _add_email(database, tenant_id, user_id, received_at=now - timedelta(weeks=3))

    async with database.session() as session:
        points = await _service(session).weekly_email_volume(user_id, weeks=6)

    assert sum(p.count for p in points) == 2
    assert all(p.count >= 0 for p in points)


@pytest.mark.asyncio
async def test_monthly_trends_reports_email_and_task_volume(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(database, tenant_id, user_id, received_at=now, priority_score=0.8)
    await _add_email(database, tenant_id, user_id, received_at=now, priority_score=0.4)

    async with database.session() as session:
        await TaskRepository(session).add(
            Task(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Do the thing",
                status="pending",
            )
        )

    async with database.session() as session:
        points = await _service(session).monthly_trends(user_id, months=3)

    current_month = next(
        p for p in points if p.month.month == now.month and p.month.year == now.year
    )
    assert current_month.email_count == 2
    assert current_month.task_count == 1
    assert current_month.avg_priority_score == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_category_distribution_counts_and_ranks(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(database, tenant_id, user_id, received_at=now, category="fyi")
    await _add_email(database, tenant_id, user_id, received_at=now, category="fyi")
    await _add_email(
        database, tenant_id, user_id, received_at=now, category="action_required"
    )
    await _add_email(database, tenant_id, user_id, received_at=now, category=None)

    async with database.session() as session:
        rows = await _service(session).category_distribution(user_id, days=30)

    assert rows[0].category == "fyi"
    assert rows[0].count == 2
    assert sum(r.count for r in rows) == 3  # uncategorized email excluded


@pytest.mark.asyncio
async def test_priority_distribution_buckets_into_fixed_bands(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(database, tenant_id, user_id, received_at=now, priority_score=0.1)
    await _add_email(database, tenant_id, user_id, received_at=now, priority_score=0.85)
    await _add_email(database, tenant_id, user_id, received_at=now, priority_score=0.95)

    async with database.session() as session:
        rows = await _service(session).priority_distribution(user_id, days=30)

    bands = {r.band: r.count for r in rows}
    assert bands["0-20"] == 1
    assert bands["80-100"] == 2
    assert bands["20-40"] == 0


@pytest.mark.asyncio
async def test_response_time_stats_computed_from_sent_drafts(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    email = await _add_email(
        database, tenant_id, user_id, received_at=now - timedelta(hours=4)
    )

    async with database.session() as session:
        await DraftReplyRepository(session).add(
            DraftReply(
                tenant_id=tenant_id,
                user_id=user_id,
                email_id=email.id,
                body_text="Reply text",
                status="sent",
                sent_at=now,
            )
        )

    async with database.session() as session:
        stats = await _service(session).response_time_stats(user_id, days=30)

    assert stats.sample_size == 1
    assert stats.average_hours == pytest.approx(4.0, abs=0.01)
    assert stats.median_hours == pytest.approx(4.0, abs=0.01)


@pytest.mark.asyncio
async def test_response_time_stats_empty_when_no_sent_drafts(
    database: Database,
) -> None:
    _tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        stats = await _service(session).response_time_stats(user_id, days=30)

    assert stats.sample_size == 0
    assert stats.average_hours is None
    assert stats.median_hours is None


@pytest.mark.asyncio
async def test_unread_summary_breaks_down_by_category_and_age(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()
    await _add_email(
        database,
        tenant_id,
        user_id,
        received_at=now - timedelta(hours=2),
        category="fyi",
        is_read=False,
    )
    await _add_email(
        database,
        tenant_id,
        user_id,
        received_at=now - timedelta(days=10),
        category="newsletter",
        is_read=False,
    )
    await _add_email(database, tenant_id, user_id, received_at=now, is_read=True)

    async with database.session() as session:
        summary = await _service(session).unread_summary(user_id)

    assert summary.total_unread == 2
    age_bands = {r.band: r.count for r in summary.by_age}
    assert age_bands["<1 day"] == 1
    assert age_bands["7+ days"] == 1


@pytest.mark.asyncio
async def test_task_completion_stats_rate_and_priority_breakdown(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = utcnow()

    async with database.session() as session:
        repo = TaskRepository(session)
        await repo.add(
            Task(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Completed high",
                status="completed",
                priority="high",
                completed_at=now,
            )
        )
        await repo.add(
            Task(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Pending high",
                status="pending",
                priority="high",
            )
        )
        await repo.add(
            Task(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Completed low",
                status="completed",
                priority="low",
                completed_at=now,
            )
        )

    async with database.session() as session:
        stats = await _service(session).task_completion_stats(user_id, days=30)

    assert stats.total_tasks == 3
    assert stats.completed_tasks == 2
    assert stats.completion_rate == pytest.approx(2 / 3)
    by_priority = {r.priority: (r.total, r.completed) for r in stats.by_priority}
    assert by_priority["high"] == (2, 1)
    assert by_priority["low"] == (1, 1)
    assert sum(p.count for p in stats.daily_completions) == 2


@pytest.mark.asyncio
async def test_full_report_combines_every_chart(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    await _add_email(database, tenant_id, user_id, received_at=utcnow(), category="fyi")

    async with database.session() as session:
        report = await _service(session).full_report(user_id, days=30)

    assert report.range_days == 30
    assert len(report.daily_email_volume) > 0
    assert len(report.weekly_email_volume) > 0
    assert len(report.monthly_trends) > 0
    assert report.category_distribution[0].category == "fyi"
    assert report.unread_summary.total_unread >= 0
