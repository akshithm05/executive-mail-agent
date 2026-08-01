"""Integration tests for reminders and the APScheduler job functions.

These test the job *functions* (``dispatch_due_reminders``,
``run_memory_decay_sweep``) directly against a real SQLite database --
the right level to verify dispatch logic without needing the actual
APScheduler timer running, matching how the rest of this suite avoids
testing framework machinery it doesn't own.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.reminder import ReminderRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.scheduler import dispatch_due_reminders, run_memory_decay_sweep
from app.services.memory import MemoryService
from app.services.reminder import ReminderService


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


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
async def test_schedule_and_list_due(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)

    async with database.session() as session:
        service = ReminderService(ReminderRepository(session))
        past = await service.schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            remind_at=now - timedelta(minutes=5),
            message="Past due reminder",
        )
        await service.schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            remind_at=now + timedelta(hours=1),
            message="Future reminder",
        )

    async with database.session() as session:
        service = ReminderService(ReminderRepository(session))
        due = await service.list_due(now=now)
        assert len(due) == 1
        assert due[0].id == past.id


@pytest.mark.asyncio
async def test_cancel_reminder_excludes_it_from_due(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)

    async with database.session() as session:
        service = ReminderService(ReminderRepository(session))
        reminder = await service.schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            remind_at=now - timedelta(minutes=1),
            message="Will be cancelled",
        )
        await service.cancel(reminder.id)

    async with database.session() as session:
        service = ReminderService(ReminderRepository(session))
        due = await service.list_due(now=now)
        assert due == []


@pytest.mark.asyncio
async def test_dispatch_due_reminders_creates_notifications(
    database: Database, settings: Settings, http_client: httpx.AsyncClient
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)

    async with database.session() as session:
        service = ReminderService(ReminderRepository(session))
        await service.schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            remind_at=now - timedelta(minutes=1),
            message='Task due soon: "Sign the contract"',
        )
        await service.schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            remind_at=now + timedelta(hours=1),
            message="Not due yet",
        )

    dispatched = await dispatch_due_reminders(
        database, settings, http_client=http_client
    )
    assert dispatched == 1

    async with database.session() as session:
        notifications = await NotificationRepository(session).list_unread(user_id)
        assert len(notifications) == 1
        assert notifications[0].type == "reminder"
        assert notifications[0].body == 'Task due soon: "Sign the contract"'

        remaining_due = await ReminderService(ReminderRepository(session)).list_due(
            now=now
        )
        assert remaining_due == []

    # Running dispatch again must not re-notify an already-sent reminder.
    assert (
        await dispatch_due_reminders(database, settings, http_client=http_client) == 0
    )
    async with database.session() as session:
        notifications = await NotificationRepository(session).list_unread(user_id)
        assert len(notifications) == 1


@pytest.mark.asyncio
async def test_dispatch_due_reminders_links_calendar_event(
    database: Database, settings: Settings, http_client: httpx.AsyncClient
) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)

    async with database.session() as session:
        event = await CalendarEventRepository(session).add(
            CalendarEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Board meeting",
                start_at=now + timedelta(hours=1),
                end_at=now + timedelta(hours=2),
            )
        )
        await ReminderService(ReminderRepository(session)).schedule(
            tenant_id=tenant_id,
            user_id=user_id,
            calendar_event_id=event.id,
            remind_at=now - timedelta(minutes=1),
            message='Upcoming: "Board meeting"',
        )

    dispatched = await dispatch_due_reminders(
        database, settings, http_client=http_client
    )
    assert dispatched == 1

    async with database.session() as session:
        notifications = await NotificationRepository(session).list_unread(user_id)
        assert len(notifications) == 1
        assert notifications[0].related_entity_type == "calendar_event"


@pytest.mark.asyncio
async def test_run_memory_decay_sweep_rescoring_count(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Some durable fact.",
        )
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Another durable fact.",
        )

    rescored = await run_memory_decay_sweep(database)
    assert rescored == 2
