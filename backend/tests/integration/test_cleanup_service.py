"""Integration tests for the scheduled cleanup sweep.

Drives :class:`CleanupService` against a real (SQLite-backed) database,
seeding rows on both sides of each retention window to confirm the sweep
purges exactly the stale ones.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.infra.db.session import Database
from app.infra.models.notification import Notification
from app.infra.models.notification_delivery import NotificationDelivery
from app.infra.models.prompt_log import PromptLog
from app.infra.models.session import Session
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.cleanup_service import CleanupService
from app.services.retry_queue import RetryQueueService


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


@pytest.mark.asyncio
async def test_cleanup_sweep_purges_only_stale_rows(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)
    stale = now - timedelta(days=120)

    async with database.session() as session:
        session_repo = SessionRepository(session)
        stale_session = await session_repo.add(
            Session(
                user_id=user_id,
                token_hash="stale" * 8,
                expires_at=stale,
            )
        )
        fresh_session = await session_repo.add(
            Session(
                user_id=user_id,
                token_hash="fresh" * 8,
                expires_at=now + timedelta(days=10),
            )
        )

        prompt_log_repo = PromptLogRepository(session)
        stale_log = await prompt_log_repo.add(
            PromptLog(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                model="test",
                prompt_text="p",
                status="success",
            )
        )
        fresh_log = await prompt_log_repo.add(
            PromptLog(
                tenant_id=tenant_id,
                user_id=user_id,
                provider="anthropic",
                model="test",
                prompt_text="p",
                status="success",
            )
        )

        notification_repo = NotificationRepository(session)
        stale_read_notification = await notification_repo.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="reminder",
                title="old",
                is_read=True,
            )
        )
        stale_unread_notification = await notification_repo.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="reminder",
                title="old but unread",
                is_read=False,
            )
        )

        retry_queue = RetryQueueService(FailedJobRepository(session))
        stale_resolved_job = await retry_queue.enqueue_failure(
            tenant_id=tenant_id,
            user_id=user_id,
            job_type="ai_triage",
            payload={},
            error="x",
        )
        await retry_queue.record_success(stale_resolved_job)

        delivery_repo = NotificationDeliveryRepository(session)
        stale_delivery = await delivery_repo.add(
            NotificationDelivery(
                tenant_id=tenant_id,
                notification_id=stale_read_notification.id,
                channel_type="webhook",
                status="sent",
            )
        )
        fresh_delivery = await delivery_repo.add(
            NotificationDelivery(
                tenant_id=tenant_id,
                notification_id=stale_unread_notification.id,
                channel_type="webhook",
                status="sent",
            )
        )

    # Backdate the "stale" rows' timestamps directly -- creation time alone
    # can't otherwise be pushed into the past through the public API.
    async with database.session() as session:
        await SessionRepository(session).update_fields(
            stale_session.id, created_at=stale
        )
        await PromptLogRepository(session).update_fields(stale_log.id, created_at=stale)
        await NotificationRepository(session).update_fields(
            stale_read_notification.id, created_at=stale
        )
        await NotificationRepository(session).update_fields(
            stale_unread_notification.id, created_at=stale
        )
        await FailedJobRepository(session).update_fields(
            stale_resolved_job.id, updated_at=stale
        )
        await NotificationDeliveryRepository(session).update_fields(
            stale_delivery.id, created_at=stale
        )

    async with database.session() as session:
        cleanup_service = CleanupService(
            SessionRepository(session),
            PromptLogRepository(session),
            NotificationRepository(session),
            RetryQueueService(FailedJobRepository(session)),
            NotificationDeliveryRepository(session),
        )
        result = await cleanup_service.run(
            session_retention_days=30,
            prompt_log_retention_days=30,
            notification_retention_days=30,
            retry_job_retention_days=30,
            notification_delivery_retention_days=30,
        )

    assert result.expired_sessions_purged == 1
    assert result.prompt_logs_purged == 1
    assert result.notifications_purged == 1
    assert result.resolved_retry_jobs_purged == 1
    assert result.notification_deliveries_purged == 1
    assert result.total == 5

    async with database.session() as session:
        assert await SessionRepository(session).get(stale_session.id) is None
        assert await SessionRepository(session).get(fresh_session.id) is not None
        assert await PromptLogRepository(session).get(stale_log.id) is None
        assert await PromptLogRepository(session).get(fresh_log.id) is not None
        assert (
            await NotificationRepository(session).get(stale_read_notification.id)
            is None
        )
        # Unread notifications are never purged, regardless of age.
        assert (
            await NotificationRepository(session).get(stale_unread_notification.id)
            is not None
        )
        assert (
            await NotificationDeliveryRepository(session).get(stale_delivery.id) is None
        )
        assert (
            await NotificationDeliveryRepository(session).get(fresh_delivery.id)
            is not None
        )
