"""Reminder repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
from app.infra.models.reminder import Reminder
from app.infra.repositories.base import SoftDeleteRepository


class ReminderRepository(SoftDeleteRepository[Reminder]):
    """Persistence operations for scheduled reminders."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Reminder)

    async def list_due(self, *, now: datetime, limit: int = 200) -> Sequence[Reminder]:
        """Return pending reminders whose ``remind_at`` has passed.

        Used by the periodic APScheduler dispatch job (see
        ``app/scheduler.py``) -- a poll-based design rather than one
        dynamically-scheduled job per reminder, so it needs no persistent
        job store and survives a process restart trivially (a reminder that
        was due while the process was down simply fires on the next poll).
        ``now`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``remind_at`` is a naive column.
        """
        stmt = (
            select(Reminder)
            .where(
                Reminder.status == "pending",
                Reminder.remind_at <= as_naive_utc(now),
                Reminder.deleted_at.is_(None),
            )
            .order_by(Reminder.remind_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(
        self, user_id: uuid.UUID, *, status: str | None = None
    ) -> Sequence[Reminder]:
        """Return a user's reminders, optionally filtered by status."""
        stmt = select(Reminder).where(
            Reminder.user_id == user_id, Reminder.deleted_at.is_(None)
        )
        if status is not None:
            stmt = stmt.where(Reminder.status == status)
        stmt = stmt.order_by(Reminder.remind_at.asc())
        result = await self._session.execute(stmt)
        return result.scalars().all()
