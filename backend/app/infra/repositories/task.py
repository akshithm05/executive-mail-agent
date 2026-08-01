"""Task repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
from app.infra.models.task import Task
from app.infra.repositories.base import SoftDeleteRepository


class TaskRepository(SoftDeleteRepository[Task]):
    """Persistence operations for tasks."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Task)

    async def list_by_status(
        self, user_id: uuid.UUID, status: str, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Task]:
        """Return a user's tasks in a given status, soonest-due first."""
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status == status,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.due_at.asc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Task]:
        """Return a user's tasks, optionally filtered by status."""
        stmt = select(Task).where(Task.user_id == user_id, Task.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Task.status == status)
        stmt = (
            stmt.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_pending(self, user_id: uuid.UUID) -> int:
        """Return the number of a user's pending or in-progress tasks."""
        stmt = select(func.count()).where(
            Task.user_id == user_id,
            Task.status.in_(("pending", "in_progress")),
            Task.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_completed_since(
        self, user_id: uuid.UUID, *, since: datetime
    ) -> int:
        """Return the number of tasks completed on/after ``since`` (weekly digest).

        ``since`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``completed_at`` is a naive column.
        """
        stmt = select(func.count()).where(
            Task.user_id == user_id,
            Task.status == "completed",
            Task.completed_at.is_not(None),
            Task.completed_at >= as_naive_utc(since),
            Task.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_analytics(
        self, user_id: uuid.UUID, *, since: datetime, limit: int = 20_000
    ) -> Sequence[Task]:
        """Return tasks relevant to a completion-rate/trend report since ``since``.

        "Relevant" means created *or* completed within the window -- a task
        created before ``since`` but completed inside it still belongs in a
        completion trend, and one created inside the window but still
        pending still belongs in the completion-rate denominator. ``since``
        is normalized to naive UTC (see ``app/core/time.py``).
        """
        naive_since = as_naive_utc(since)
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                or_(
                    Task.created_at >= naive_since,
                    Task.completed_at >= naive_since,
                ),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
