"""Reminder service.

Reminders are created by the email-triage graph (one per task with a due
date, one per AI-suggested calendar event -- see
``app/agents/graph.py::database_update``) and dispatched by a periodic
APScheduler job (see ``app/scheduler.py``) that turns a due reminder into a
:class:`~app.infra.models.notification.Notification`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from app.core.time import utcnow
from app.infra.models.reminder import Reminder
from app.infra.repositories.reminder import ReminderRepository
from app.services.crud import CRUDService


class ReminderService(CRUDService[Reminder]):
    """CRUD operations for reminders, plus dispatch-lifecycle helpers."""

    def __init__(self, repository: ReminderRepository) -> None:
        super().__init__(repository)
        self._repo: ReminderRepository = repository

    async def list_by_user(
        self, user_id: uuid.UUID, *, status: str | None = None
    ) -> Sequence[Reminder]:
        """Return a user's reminders, optionally filtered by status."""
        return await self._repo.list_by_user(user_id, status=status)

    async def list_due(self, *, now: datetime | None = None) -> Sequence[Reminder]:
        """Return pending reminders whose ``remind_at`` has passed."""
        return await self._repo.list_due(now=now or utcnow())

    async def schedule(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        remind_at: datetime,
        message: str,
        task_id: uuid.UUID | None = None,
        calendar_event_id: uuid.UUID | None = None,
    ) -> Reminder:
        """Create a new pending reminder."""
        return await self.create(
            Reminder(
                tenant_id=tenant_id,
                user_id=user_id,
                task_id=task_id,
                calendar_event_id=calendar_event_id,
                remind_at=remind_at,
                message=message,
                status="pending",
            )
        )

    async def mark_sent(self, reminder_id: uuid.UUID) -> Reminder | None:
        """Mark a reminder as dispatched."""
        return await self.update(reminder_id, status="sent", sent_at=utcnow())

    async def cancel(self, reminder_id: uuid.UUID) -> Reminder | None:
        """Cancel a pending reminder (e.g. its task was completed early)."""
        return await self.update(reminder_id, status="cancelled")
