"""Integration tests for the Phase 9 dashboard read/write API routes.

Driven over real HTTP through the logged-in session (``logged_in_client``),
against a real (SQLite-backed) database -- no mocking of route handlers,
services, or repositories.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.infra.db.session import Database
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.email import Email
from app.infra.models.notification import Notification
from app.infra.models.task import Task
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


async def _get_current_user(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        return user.tenant_id, user.id


async def _seed_email(
    database: Database, *, tenant_id: uuid.UUID, user_id: uuid.UUID, **overrides: object
) -> Email:
    defaults: dict[str, object] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "gmail_message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "gmail_thread_id": "thread-1",
        "subject": "Contract needs your signature",
        "from_address": "client@example.com",
        "received_at": datetime.now(UTC),
        "category": "action_required",
        "priority_score": 0.85,
    }
    defaults.update(overrides)
    async with database.session() as session:
        email = await EmailRepository(session).add(Email(**defaults))  # type: ignore[arg-type]
    return email


@pytest.mark.asyncio
async def test_dashboard_routes_require_authentication(client: AsyncClient) -> None:
    for path in (
        "/api/v1/emails",
        "/api/v1/tasks",
        "/api/v1/calendar-events",
        "/api/v1/notifications",
        "/api/v1/preferences",
        "/api/v1/dashboard/summary",
    ):
        response = await client.get(path)
        assert response.status_code == 401, path


@pytest.mark.asyncio
async def test_list_and_filter_emails(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    await _seed_email(database, tenant_id=tenant_id, user_id=user_id, category="fyi")
    await _seed_email(
        database,
        tenant_id=tenant_id,
        user_id=user_id,
        category="action_required",
        priority_score=0.9,
    )

    response = await logged_in_client.get("/api/v1/emails")
    assert response.status_code == 200
    assert len(response.json()) == 2

    filtered = await logged_in_client.get("/api/v1/emails", params={"category": "fyi"})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["category"] == "fyi"


@pytest.mark.asyncio
async def test_urgent_and_deadline_email_lists(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    await _seed_email(
        database,
        tenant_id=tenant_id,
        user_id=user_id,
        category="newsletter",
        priority_score=0.1,
    )
    await _seed_email(
        database,
        tenant_id=tenant_id,
        user_id=user_id,
        category="action_required",
        priority_score=0.95,
        has_deadline=True,
        deadline_at=datetime.now(UTC) + timedelta(days=1),
    )

    urgent = await logged_in_client.get("/api/v1/emails/urgent")
    assert urgent.status_code == 200
    assert len(urgent.json()) == 1
    assert urgent.json()[0]["category"] == "action_required"

    deadlines = await logged_in_client.get("/api/v1/emails/deadlines")
    assert deadlines.status_code == 200
    assert len(deadlines.json()) == 1


@pytest.mark.asyncio
async def test_get_and_mark_email_read(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    email = await _seed_email(database, tenant_id=tenant_id, user_id=user_id)

    detail = await logged_in_client.get(f"/api/v1/emails/{email.id}")
    assert detail.status_code == 200
    assert detail.json()["is_read"] is False

    marked = await logged_in_client.post(f"/api/v1/emails/{email.id}/read")
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True


@pytest.mark.asyncio
async def test_email_not_owned_returns_404(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, _user_id = await _get_current_user(database)
    other_user_id = uuid.uuid4()
    async with database.session() as session:
        from app.infra.models.user import User

        other_user = await UserRepository(session).add(
            User(
                tenant_id=tenant_id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
        other_user_id = other_user.id
    email = await _seed_email(database, tenant_id=tenant_id, user_id=other_user_id)

    response = await logged_in_client.get(f"/api/v1/emails/{email.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_task_list_edit_and_complete(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    async with database.session() as session:
        task = await TaskRepository(session).add(
            Task(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Sign the contract",
                priority="high",
            )
        )

    listed = await logged_in_client.get("/api/v1/tasks")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    edited = await logged_in_client.patch(
        f"/api/v1/tasks/{task.id}", json={"priority": "urgent"}
    )
    assert edited.status_code == 200
    assert edited.json()["priority"] == "urgent"

    completed = await logged_in_client.post(f"/api/v1/tasks/{task.id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_list_upcoming_calendar_events(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    now = datetime.now(UTC)
    async with database.session() as session:
        repo = CalendarEventRepository(session)
        await repo.add(
            CalendarEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Past meeting",
                start_at=now - timedelta(days=1),
                end_at=now - timedelta(days=1, hours=-1),
            )
        )
        await repo.add(
            CalendarEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Upcoming sync",
                start_at=now + timedelta(days=1),
                end_at=now + timedelta(days=1, hours=1),
            )
        )

    response = await logged_in_client.get("/api/v1/calendar-events")
    assert response.status_code == 200
    titles = {e["title"] for e in response.json()}
    assert titles == {"Upcoming sync"}


@pytest.mark.asyncio
async def test_notifications_list_and_mark_read(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    async with database.session() as session:
        notification = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="reminder",
                title="Task due soon",
                body="Sign the contract",
            )
        )

    listed = await logged_in_client.get("/api/v1/notifications")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["is_read"] is False

    marked = await logged_in_client.post(
        f"/api/v1/notifications/{notification.id}/read"
    )
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    unread_only = await logged_in_client.get(
        "/api/v1/notifications", params={"unread_only": True}
    )
    assert unread_only.json() == []


@pytest.mark.asyncio
async def test_preferences_set_and_list(logged_in_client: AsyncClient) -> None:
    set_response = await logged_in_client.put(
        "/api/v1/preferences/theme",
        json={"value": {"mode": "dark"}, "category": "ui"},
    )
    assert set_response.status_code == 200
    assert set_response.json()["value"] == {"mode": "dark"}

    listed = await logged_in_client.get("/api/v1/preferences")
    assert listed.status_code == 200
    assert any(p["key"] == "theme" for p in listed.json())

    # Upsert: setting the same key again updates rather than duplicating.
    await logged_in_client.put(
        "/api/v1/preferences/theme", json={"value": {"mode": "light"}}
    )
    listed_again = await logged_in_client.get("/api/v1/preferences")
    theme_prefs = [p for p in listed_again.json() if p["key"] == "theme"]
    assert len(theme_prefs) == 1
    assert theme_prefs[0]["value"] == {"mode": "light"}


@pytest.mark.asyncio
async def test_dashboard_summary_aggregates_everything(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    await _seed_email(
        database,
        tenant_id=tenant_id,
        user_id=user_id,
        category="action_required",
        priority_score=0.9,
        is_read=False,
        has_deadline=True,
        deadline_at=datetime.now(UTC) + timedelta(hours=6),
    )
    await _seed_email(
        database,
        tenant_id=tenant_id,
        user_id=user_id,
        category="newsletter",
        priority_score=0.2,
    )
    async with database.session() as session:
        await TaskRepository(session).add(
            Task(tenant_id=tenant_id, user_id=user_id, title="Follow up")
        )
        await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="reminder",
                title="Heads up",
            )
        )

    response = await logged_in_client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_emails"] == 2
    assert body["unread_emails"] == 2
    assert body["urgent_emails"] == 1
    assert body["upcoming_deadlines"] == 1
    assert body["pending_tasks"] == 1
    assert body["unread_notifications"] == 1
    assert body["category_counts"]["action_required"] == 1
    assert body["category_counts"]["newsletter"] == 1
    assert len(body["priority_heatmap"]) == 2
