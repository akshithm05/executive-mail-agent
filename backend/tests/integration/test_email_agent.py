"""Integration tests for the email-triage LangGraph agent.

Drives :func:`~app.agents.email_agent.run_email_triage` against a real
(SQLite-backed) database and the fake Anthropic server -- real HTTP, real
JSON, the exact wire contract verified against the installed SDK's own
source (see ``tests/fake_anthropic/app.py``) -- rather than mocking the
graph, the LLM client, or Claude's responses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from app.agents.email_agent import run_email_triage
from app.config.settings import AISettings, Settings
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.queue import AIProcessingJob
from app.infra.repositories.ai_history import AIHistoryRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.reminder import ReminderRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from httpx import ASGITransport

from tests.fake_anthropic.app import FakeAnthropicState, create_fake_anthropic_app


async def _seed_email(database: Database) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
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
        email = await EmailRepository(session).add(
            Email(
                tenant_id=tenant.id,
                user_id=user.id,
                gmail_message_id="msg-1",
                gmail_thread_id="thread-1",
                subject="Contract needs your signature",
                from_address="client@example.com",
                body_text="Please sign and return the attached contract by Friday.",
                received_at=datetime.now(UTC),
            )
        )
    return tenant.id, user.id, email.id


def _settings_with_ai() -> Settings:
    return Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        ai=AISettings(anthropic_api_key="test-key"),
    )


@pytest.mark.asyncio
async def test_email_triage_happy_path(database: Database) -> None:
    _tenant_id, user_id, email_id = await _seed_email(database)
    fake_app = create_fake_anthropic_app()
    state: FakeAnthropicState = fake_app.state.fake_anthropic

    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        job = AIProcessingJob(
            tenant_id=_tenant_id,
            user_id=user_id,
            email_id=email_id,
            gmail_message_id="msg-1",
        )
        await run_email_triage(
            job, database, _settings_with_ai(), http_client=http_client
        )

    assert state.call_count > 0

    async with database.session() as session:
        histories = await AIHistoryRepository(session).list_by_user(user_id)
        assert len(histories) == 1
        history = histories[0]
        assert history.extra_metadata["category"] == "action_required"
        assert history.extra_metadata["task_count"] == 1
        assert history.extra_metadata["should_reply"] is True
        assert history.extra_metadata["errors"] == []

        tasks = await TaskRepository(session).list_by_status(user_id, "pending")
        assert len(tasks) == 1
        assert tasks[0].title == "Sign and return the contract"
        assert tasks[0].email_id == email_id
        assert tasks[0].created_by == "ai"

        drafts = await DraftReplyRepository(session).list_by_email(email_id)
        assert len(drafts) == 1
        assert drafts[0].body_text

        notifications = await NotificationRepository(session).list_unread(user_id)
        assert len(notifications) == 1
        assert notifications[0].type == "draft_ready"

        prompt_logs = await PromptLogRepository(session).list_by_ai_history(history.id)
        # One LLM call per node that ran, plus the tool-call context fetch.
        assert len(prompt_logs) >= 6
        assert all(log.status == "success" for log in prompt_logs)


@pytest.mark.asyncio
async def test_email_triage_degrades_gracefully_on_node_failure(
    database: Database,
) -> None:
    """Verify one failing node degrades instead of crashing the pipeline.

    ``categorize`` fails on every attempt; the pipeline still completes end
    to end with a safe default, and every other node still runs and
    persists its own results.
    """
    _tenant_id, user_id, email_id = await _seed_email(database)
    fake_app = create_fake_anthropic_app()
    state: FakeAnthropicState = fake_app.state.fake_anthropic
    state.fail_fields.add("category")

    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        job = AIProcessingJob(
            tenant_id=_tenant_id,
            user_id=user_id,
            email_id=email_id,
            gmail_message_id="msg-1",
        )
        await run_email_triage(
            job, database, _settings_with_ai(), http_client=http_client
        )

    async with database.session() as session:
        histories = await AIHistoryRepository(session).list_by_user(user_id)
        assert len(histories) == 1
        history = histories[0]
        assert history.extra_metadata["category"] == "other"  # safe default
        errors = history.extra_metadata["errors"]
        assert len(errors) == 1
        assert errors[0]["node"] == "categorize"

        # Every downstream node still ran and persisted its own results.
        tasks = await TaskRepository(session).list_by_status(user_id, "pending")
        assert len(tasks) == 1

        prompt_logs = await PromptLogRepository(session).list_by_ai_history(history.id)
        assert any(log.status == "error" for log in prompt_logs)
        assert any(log.status == "success" for log in prompt_logs)


@pytest.mark.asyncio
async def test_email_triage_wires_task_deadlines_dependencies_and_reminders(
    database: Database,
) -> None:
    """Task extraction's due_at/depends_on_index reach real rows.

    A task with a due date also gets a reminder scheduled -- this exercises
    the Phase 8 wiring added to ``database_update`` (deadline extraction,
    task dependency resolution, reminder scheduling) end to end.
    """
    _tenant_id, user_id, email_id = await _seed_email(database)
    fake_app = create_fake_anthropic_app()
    state: FakeAnthropicState = fake_app.state.fake_anthropic
    state.overrides["tasks"] = {
        "tasks": [
            {
                "title": "Review the draft contract",
                "description": "Read through before signing.",
                "priority": "high",
                "due_at": "2026-08-01T12:00:00+00:00",
                "depends_on_index": None,
            },
            {
                "title": "Sign and return the contract",
                "description": "",
                "priority": "high",
                "due_at": "2026-08-01T17:00:00+00:00",
                "depends_on_index": 0,
            },
        ],
        "confidence": 0.8,
    }

    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        job = AIProcessingJob(
            tenant_id=_tenant_id,
            user_id=user_id,
            email_id=email_id,
            gmail_message_id="msg-1",
        )
        await run_email_triage(
            job, database, _settings_with_ai(), http_client=http_client
        )

    async with database.session() as session:
        tasks = await TaskRepository(session).list_by_status(user_id, "pending")
        assert len(tasks) == 2
        by_title = {t.title: t for t in tasks}
        review = by_title["Review the draft contract"]
        sign = by_title["Sign and return the contract"]

        assert review.due_at is not None
        assert review.depends_on_task_id is None
        assert sign.due_at is not None
        assert sign.depends_on_task_id == review.id

        reminders = await ReminderRepository(session).list_by_user(user_id)
        assert len(reminders) == 2
        reminder_task_ids = {r.task_id for r in reminders}
        assert reminder_task_ids == {review.id, sign.id}
        assert all(r.status == "pending" for r in reminders)
