"""Integration tests for the Phase 3 domain models.

Builds a realistic object graph across all fourteen entities against the
real (SQLite-backed) database used by the test suite -- exercising actual
relationships, cascade/SET NULL FK behavior, unique/check constraints, and
soft-delete filtering, not mocks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.exceptions import ConflictError
from app.infra.db.session import Database
from app.infra.models.ai_history import AIHistory
from app.infra.models.attachment import Attachment
from app.infra.models.audit_log import AuditLog
from app.infra.models.calendar_event import CalendarEvent
from app.infra.models.draft_reply import DraftReply
from app.infra.models.email import Email
from app.infra.models.label import Label
from app.infra.models.memory import Memory
from app.infra.models.notification import Notification
from app.infra.models.prompt_log import PromptLog
from app.infra.models.summary import Summary
from app.infra.models.task import Task
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.ai_history import AIHistoryRepository
from app.infra.repositories.attachment import AttachmentRepository
from app.infra.repositories.audit_log import AuditLogRepository
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.label import EmailLabelRepository, LabelRepository
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.preference import PreferenceRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.summary import SummaryRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.audit_log import AuditLogService
from app.services.crud import CRUDService
from app.services.label import LabelService
from app.services.notification import NotificationService
from app.services.preference import PreferenceService
from app.services.task import TaskService
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


async def _seed_tenant_user_email(session: AsyncSession) -> tuple[Tenant, User, Email]:
    tenant = await TenantRepository(session).add(
        Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", plan="pro")
    )
    user = await UserRepository(session).add(
        User(
            tenant_id=tenant.id,
            google_subject=f"sub-{uuid.uuid4().hex[:8]}",
            email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            display_name="Exec User",
        )
    )
    email = await EmailRepository(session).add(
        Email(
            tenant_id=tenant.id,
            user_id=user.id,
            gmail_message_id="msg-1",
            gmail_thread_id="thread-1",
            subject="Quarterly numbers",
            from_address="cfo@example.com",
            received_at=datetime.now(UTC),
        )
    )
    return tenant, user, email


@pytest.mark.asyncio
async def test_full_domain_graph_creates_and_relates(
    database: Database, now: datetime
) -> None:
    """Build one instance of every Phase 3 entity and verify relationships load."""
    async with database.session() as session:
        tenant, user, email = await _seed_tenant_user_email(session)

        attachment = await AttachmentRepository(session).add(
            Attachment(
                tenant_id=tenant.id,
                email_id=email.id,
                gmail_attachment_id="att-1",
                filename="report.pdf",
                mime_type="application/pdf",
                size_bytes=2048,
            )
        )

        label_repo = LabelRepository(session)
        label_service = LabelService(label_repo, EmailLabelRepository(session))
        label = await label_service.create(
            Label(tenant_id=tenant.id, user_id=user.id, name="Finance", type="user")
        )
        await label_service.assign(email.id, label.id)

        task = await TaskRepository(session).add(
            Task(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                title="Review quarterly numbers",
                created_by="ai",
            )
        )

        calendar_event = await CalendarEventRepository(session).add(
            CalendarEvent(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                title="Finance review",
                start_at=now + timedelta(days=1),
                end_at=now + timedelta(days=1, hours=1),
            )
        )

        draft_reply = await DraftReplyRepository(session).add(
            DraftReply(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                body_text="Thanks, looks good.",
            )
        )

        ai_history = await AIHistoryRepository(session).add(
            AIHistory(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                task_id=task.id,
                action_type="triage",
                model_name="test-model",
            )
        )

        prompt_log = await PromptLogRepository(session).add(
            PromptLog(
                tenant_id=tenant.id,
                user_id=user.id,
                ai_history_id=ai_history.id,
                provider="anthropic",
                model="claude",
                prompt_text="Summarize this email.",
                response_text="Summary text.",
            )
        )

        summary = await SummaryRepository(session).add(
            Summary(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                content="Short summary.",
            )
        )

        memory = await MemoryRepository(session).add(
            Memory(
                tenant_id=tenant.id,
                user_id=user.id,
                source_email_id=email.id,
                content="User prefers concise replies.",
            )
        )

        notification = await NotificationRepository(session).add(
            Notification(
                tenant_id=tenant.id,
                user_id=user.id,
                type="draft_ready",
                title="A draft reply is ready",
            )
        )

        audit_log = await AuditLogRepository(session).add(
            AuditLog(tenant_id=tenant.id, user_id=user.id, action="login")
        )

        preference_service = PreferenceService(PreferenceRepository(session))
        preference = await preference_service.set(
            tenant.id, user.id, "digest_frequency", {"value": "daily"}
        )

        await session.flush()

        # -- Relationship traversal (ORM loads real rows, not stubs) --------
        await session.refresh(email, attribute_names=["attachments", "tasks"])
        assert [a.id for a in email.attachments] == [attachment.id]
        assert [t.id for t in email.tasks] == [task.id]

        await session.refresh(email, attribute_names=["labels"])
        assert [label_row.id for label_row in email.labels] == [label.id]

        assert task.email_id == email.id
        assert calendar_event.email_id == email.id
        assert draft_reply.email_id == email.id
        assert ai_history.task_id == task.id
        assert prompt_log.ai_history_id == ai_history.id
        assert summary.email_id == email.id
        assert memory.source_email_id == email.id
        assert notification.user_id == user.id
        assert audit_log.action == "login"
        assert preference.value == {"value": "daily"}


@pytest.mark.asyncio
async def test_email_soft_delete_excludes_from_reads_but_keeps_the_row(
    database: Database,
) -> None:
    async with database.session() as session:
        _tenant, _user, email = await _seed_tenant_user_email(session)
        repo = EmailRepository(session)

        deleted = await repo.soft_delete(email.id)
        assert deleted is True

        assert await repo.get(email.id) is None
        assert email not in await repo.list()

        # The row itself is untouched -- only excluded by the repository.
        raw = await session.get(Email, email.id)
        assert raw is not None
        assert raw.deleted_at is not None


@pytest.mark.asyncio
async def test_duplicate_gmail_message_id_per_user_violates_unique_constraint(
    database: Database,
) -> None:
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        with pytest.raises(IntegrityError):
            await EmailRepository(session).add(
                Email(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    gmail_message_id="msg-1",  # same as _seed_tenant_user_email
                    gmail_thread_id="thread-1",
                    from_address="cfo@example.com",
                    received_at=datetime.now(UTC),
                )
            )
        # The failed flush leaves the session unusable until rolled back;
        # without this, the enclosing `database.session()` context manager's
        # exit-time commit raises PendingRollbackError instead of committing.
        await session.rollback()


@pytest.mark.asyncio
async def test_task_status_check_constraint_rejects_invalid_value(
    database: Database,
) -> None:
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        with pytest.raises(IntegrityError):
            await TaskRepository(session).add(
                Task(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    title="Bad status",
                    status="not_a_real_status",
                )
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_deleting_email_sets_null_on_task_but_cascades_draft_reply(
    database: Database,
) -> None:
    """Verify the documented FK-action design.

    Task survives (SET NULL); DraftReply does not (CASCADE), because a draft
    reply is meaningless without the email it replies to.
    """
    async with database.session() as session:
        tenant, user, email = await _seed_tenant_user_email(session)
        task = await TaskRepository(session).add(
            Task(tenant_id=tenant.id, user_id=user.id, email_id=email.id, title="T")
        )
        draft = await DraftReplyRepository(session).add(
            DraftReply(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                body_text="body",
            )
        )
        task_id, draft_id, email_id = task.id, draft.id, email.id
        await session.flush()

        await session.delete(await session.get(Email, email_id))
        await session.flush()

        surviving_task = await session.get(Task, task_id)
        assert surviving_task is not None
        assert surviving_task.email_id is None

        deleted_draft = await session.get(DraftReply, draft_id)
        assert deleted_draft is None


@pytest.mark.asyncio
async def test_label_assign_twice_raises_conflict(database: Database) -> None:
    async with database.session() as session:
        tenant, user, email = await _seed_tenant_user_email(session)
        service = LabelService(LabelRepository(session), EmailLabelRepository(session))
        label = await service.create(
            Label(tenant_id=tenant.id, user_id=user.id, name="Urgent")
        )
        await service.assign(email.id, label.id)

        with pytest.raises(ConflictError):
            await service.assign(email.id, label.id)

        assert await service.unassign(email.id, label.id) is True
        assert await service.unassign(email.id, label.id) is False


@pytest.mark.asyncio
async def test_preference_upsert_updates_existing_row(database: Database) -> None:
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        service = PreferenceService(PreferenceRepository(session))

        first = await service.set(tenant.id, user.id, "theme", {"value": "dark"})
        second = await service.set(tenant.id, user.id, "theme", {"value": "light"})

        assert first.id == second.id
        assert second.value == {"value": "light"}
        assert await service.count() == 1


@pytest.mark.asyncio
async def test_notification_mark_read(database: Database) -> None:
    async with database.session() as session:
        _tenant, user, _email = await _seed_tenant_user_email(session)
        service = NotificationService(NotificationRepository(session))
        notification = await service.create(
            Notification(
                tenant_id=_tenant.id, user_id=user.id, type="draft_ready", title="Hi"
            )
        )
        assert notification.is_read is False

        unread = await service.list_unread(user.id)
        assert [n.id for n in unread] == [notification.id]

        updated = await service.mark_read(notification.id)
        assert updated is not None
        assert updated.is_read is True
        assert updated.read_at is not None
        assert await service.list_unread(user.id) == []


@pytest.mark.asyncio
async def test_task_service_complete_transition(database: Database) -> None:
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        service = TaskService(TaskRepository(session))
        task = await service.create(
            Task(tenant_id=tenant.id, user_id=user.id, title="Ship it")
        )

        assert (await service.list_by_status(user.id, "pending"))[0].id == task.id

        completed = await service.complete(task.id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.completed_at is not None
        assert await service.list_by_status(user.id, "pending") == []


@pytest.mark.asyncio
async def test_audit_log_service_exposes_no_mutation_methods(
    database: Database,
) -> None:
    """Verify AuditLogService intentionally does not subclass CRUDService.

    An audit trail the application can edit or hide defeats its purpose.
    """
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        service = AuditLogService(AuditLogRepository(session))
        entry = await service.record(
            AuditLog(tenant_id=tenant.id, user_id=user.id, action="password_reset")
        )

        assert not isinstance(service, CRUDService)
        assert not hasattr(service, "update")
        assert not hasattr(service, "delete")

        trail = await service.list_by_entity("user", user.id)
        assert trail == []  # entity_type/entity_id weren't set on this entry

        fetched = await service.get(entry.id)
        assert fetched is not None
        assert fetched.action == "password_reset"


@pytest.mark.asyncio
async def test_calendar_event_list_in_range(database: Database, now: datetime) -> None:
    async with database.session() as session:
        tenant, user, _email = await _seed_tenant_user_email(session)
        repo = CalendarEventRepository(session)
        in_range = await repo.add(
            CalendarEvent(
                tenant_id=tenant.id,
                user_id=user.id,
                title="In range",
                start_at=now + timedelta(hours=2),
                end_at=now + timedelta(hours=3),
            )
        )
        await repo.add(
            CalendarEvent(
                tenant_id=tenant.id,
                user_id=user.id,
                title="Out of range",
                start_at=now + timedelta(days=10),
                end_at=now + timedelta(days=10, hours=1),
            )
        )

        results = await repo.list_in_range(user.id, now, now + timedelta(hours=6))
        assert [e.id for e in results] == [in_range.id]


@pytest.mark.asyncio
async def test_user_soft_delete_excludes_from_lookup_by_google_subject(
    database: Database,
) -> None:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="T", slug=f"t-{uuid.uuid4().hex[:8]}")
        )
        repo = UserRepository(session)
        user = await repo.add(
            User(
                tenant_id=tenant.id,
                google_subject="sub-xyz",
                email="a@example.com",
            )
        )

        assert await repo.get_by_google_subject("sub-xyz") is not None
        await repo.soft_delete(user.id)
        assert await repo.get_by_google_subject("sub-xyz") is None


@pytest.mark.asyncio
async def test_ai_history_and_prompt_log_relationship(database: Database) -> None:
    async with database.session() as session:
        tenant, user, email = await _seed_tenant_user_email(session)
        ai_history = await AIHistoryRepository(session).add(
            AIHistory(
                tenant_id=tenant.id,
                user_id=user.id,
                email_id=email.id,
                action_type="draft_generation",
            )
        )
        log_repo = PromptLogRepository(session)
        await log_repo.add(
            PromptLog(
                tenant_id=tenant.id,
                user_id=user.id,
                ai_history_id=ai_history.id,
                provider="anthropic",
                model="claude",
                prompt_text="p",
            )
        )
        await log_repo.add(
            PromptLog(
                tenant_id=tenant.id,
                user_id=user.id,
                ai_history_id=ai_history.id,
                provider="anthropic",
                model="claude",
                prompt_text="p2",
                status="error",
                error_message="boom",
            )
        )

        logs = await log_repo.list_by_ai_history(ai_history.id)
        assert len(logs) == 2
        assert {log.status for log in logs} == {"success", "error"}
