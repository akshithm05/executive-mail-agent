"""Integration tests for :class:`NotificationDispatchService`.

Drives the full pipeline (rules -> quiet hours -> fan-out -> delivery log ->
retry queue) against a real SQLite database. Every channel sender is a fake
recording its calls -- the point of these tests is the *orchestration*
(who gets called, when, and what gets logged/retried), not the individual
senders' own HTTP behavior (see ``tests/unit/test_notification_senders.py``
for that).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from app.core.crypto import TokenCipher
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.models.notification import Notification
from app.infra.models.notification_channel_config import NotificationChannelConfig
from app.infra.models.notification_quiet_hours import NotificationQuietHours
from app.infra.models.notification_rule import NotificationRule
from app.infra.models.push_device import PushDevice
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.notification_quiet_hours import (
    NotificationQuietHoursRepository,
)
from app.infra.repositories.notification_rule import NotificationRuleRepository
from app.infra.repositories.push_device import PushDeviceRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.notification_dispatch import (
    ChannelSenders,
    NotificationDispatchService,
)
from app.services.notifications.errors import (
    ChannelDeliveryError,
    DeviceUnregisteredError,
)
from app.services.retry_queue import RetryQueueService

_CIPHER = TokenCipher("uXpM2wUqBkMfjUlojjT8YEf_tEiiKRknmmhWebNIWrY=")


class _FakeSender:
    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with


def _fake_senders(
    *, webhook: _FakeSender | None = None, desktop_push: _FakeSender | None = None
) -> ChannelSenders:
    blank = _FakeSender()
    return ChannelSenders(
        slack=blank,  # type: ignore[arg-type]
        discord=blank,  # type: ignore[arg-type]
        telegram=blank,  # type: ignore[arg-type]
        whatsapp=blank,  # type: ignore[arg-type]
        webhook=webhook or blank,  # type: ignore[arg-type]
        email=blank,  # type: ignore[arg-type]
        desktop_push=desktop_push or blank,  # type: ignore[arg-type]
        mobile_push=blank,  # type: ignore[arg-type]
    )


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


def _build_service(
    database_session: Any, *, senders: ChannelSenders, max_attempts: int = 5
) -> NotificationDispatchService:
    return NotificationDispatchService(
        notification_repo=NotificationRepository(database_session),
        channel_config_repo=NotificationChannelConfigRepository(database_session),
        push_device_repo=PushDeviceRepository(database_session),
        rule_repo=NotificationRuleRepository(database_session),
        quiet_hours_repo=NotificationQuietHoursRepository(database_session),
        delivery_repo=NotificationDeliveryRepository(database_session),
        user_repo=UserRepository(database_session),
        retry_queue=RetryQueueService(FailedJobRepository(database_session)),
        cipher=_CIPHER,
        senders=senders,
        max_attempts=max_attempts,
    )


@pytest.mark.asyncio
async def test_dispatch_skips_when_no_enabled_rule_matches(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    webhook_sender = _FakeSender()

    async with database.session() as session:
        await NotificationRuleRepository(session).add(
            NotificationRule(
                tenant_id=tenant_id,
                user_id=user_id,
                name="only important",
                is_enabled=True,
                only_important=True,
            )
        )
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id, user_id=user_id, type="reminder", title="Reminder"
            )
        )
        service = _build_service(session, senders=_fake_senders(webhook=webhook_sender))
        await service.dispatch(note)

    assert webhook_sender.calls == []
    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note.id
        )
        assert len(deliveries) == 1
        assert deliveries[0].status == "skipped_rule"


@pytest.mark.asyncio
async def test_dispatch_sends_through_enabled_webhook_channel(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    webhook_sender = _FakeSender()

    async with database.session() as session:
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="reminder",
                title="Reminder",
                body="hi",
            )
        )
        service = _build_service(session, senders=_fake_senders(webhook=webhook_sender))
        await service.dispatch(note)

    assert len(webhook_sender.calls) == 1
    assert webhook_sender.calls[0]["title"] == "Reminder"
    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note.id
        )
        assert len(deliveries) == 1
        assert deliveries[0].status == "sent"
        assert deliveries[0].channel_type == "webhook"


@pytest.mark.asyncio
async def test_dispatch_logs_failure_and_enqueues_retry(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    failing_sender = _FakeSender(fail_with=ChannelDeliveryError("boom"))

    async with database.session() as session:
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id, user_id=user_id, type="reminder", title="R"
            )
        )
        service = _build_service(session, senders=_fake_senders(webhook=failing_sender))
        await service.dispatch(note)

    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note.id
        )
        assert deliveries[0].status == "failed"
        assert "boom" in (deliveries[0].error_message or "")

        jobs = await FailedJobRepository(session).list_by_tenant(tenant_id)
        matching = [j for j in jobs if j.job_type == "notification_delivery"]
        assert len(matching) == 1
        assert matching[0].payload["channel_type"] == "webhook"
        assert matching[0].payload["notification_id"] == str(note.id)
        # Scheduled with the standard near-term backoff, not immediately due.
        assert matching[0].next_attempt_at > utcnow()


@pytest.mark.asyncio
async def test_dispatch_defers_during_quiet_hours(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    webhook_sender = _FakeSender()
    now = utcnow()
    # A 2-hour window straddling "now" (started an hour ago, ends in an
    # hour) -- guaranteed to contain the current time regardless of when
    # this test runs, and narrow enough to never degenerate into a
    # zero-width (start == end) window.
    start = (now - timedelta(hours=1)).time()
    end = (now + timedelta(hours=1)).time()

    async with database.session() as session:
        await NotificationQuietHoursRepository(session).add(
            NotificationQuietHours(
                tenant_id=tenant_id,
                user_id=user_id,
                is_enabled=True,
                start_time=start,
                end_time=end,
                timezone="UTC",
                allow_urgent_override=True,
            )
        )
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        # A non-urgent notification type -- must be deferred, not sent.
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="morning_digest",
                title="Digest",
            )
        )
        service = _build_service(session, senders=_fake_senders(webhook=webhook_sender))
        await service.dispatch(note)

    assert webhook_sender.calls == []
    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note.id
        )
        assert deliveries[0].status == "deferred"
        jobs = await FailedJobRepository(session).list_by_tenant(tenant_id)
        matching = [j for j in jobs if j.job_type == "notification_delivery"]
        assert len(matching) == 1
        # Scheduled for later, not immediately due.
        assert matching[0].next_attempt_at > now + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_dispatch_urgent_notification_bypasses_quiet_hours(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    webhook_sender = _FakeSender()
    now = utcnow()
    start = (now - timedelta(hours=1)).time()
    end = (now + timedelta(hours=1)).time()

    async with database.session() as session:
        await NotificationQuietHoursRepository(session).add(
            NotificationQuietHours(
                tenant_id=tenant_id,
                user_id=user_id,
                is_enabled=True,
                start_time=start,
                end_time=end,
                timezone="UTC",
                allow_urgent_override=True,
            )
        )
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="high_priority_email",
                title="Urgent",
            )
        )
        service = _build_service(session, senders=_fake_senders(webhook=webhook_sender))
        await service.dispatch(note)

    assert len(webhook_sender.calls) == 1
    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note.id
        )
        assert deliveries[0].status == "sent"


@pytest.mark.asyncio
async def test_dispatch_deactivates_unregistered_push_device(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    dead_push_sender = _FakeSender(fail_with=DeviceUnregisteredError("gone"))

    async with database.session() as session:
        device = await PushDeviceRepository(session).add(
            PushDevice(
                tenant_id=tenant_id,
                user_id=user_id,
                platform="web",
                token_ciphertext=_CIPHER.encrypt(
                    json.dumps({"endpoint": "https://push.test/x", "keys": {}})
                ),
                is_active=True,
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id, user_id=user_id, type="reminder", title="R"
            )
        )
        service = _build_service(
            session, senders=_fake_senders(desktop_push=dead_push_sender)
        )
        await service.dispatch(note)

    async with database.session() as session:
        refreshed = await PushDeviceRepository(session).get(device.id)
        assert refreshed is not None
        assert refreshed.is_active is False
        # A dead device is never retried -- no notification_delivery job.
        jobs = await FailedJobRepository(session).list_by_tenant(tenant_id)
        assert [j for j in jobs if j.job_type == "notification_delivery"] == []


@pytest.mark.asyncio
async def test_retry_one_resends_a_single_failed_channel(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=_CIPHER.encrypt(
                    json.dumps({"url": "https://x.test"})
                ),
            )
        )
        note = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id, user_id=user_id, type="reminder", title="R"
            )
        )
        note_id = note.id

    retry_sender = _FakeSender()
    async with database.session() as session:
        service = _build_service(session, senders=_fake_senders(webhook=retry_sender))
        await service.retry_one(
            notification_id=note_id, channel_type="webhook", target="singleton"
        )

    assert len(retry_sender.calls) == 1
    async with database.session() as session:
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            note_id
        )
        assert deliveries[-1].status == "sent"
