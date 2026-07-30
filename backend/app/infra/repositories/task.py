"""Task repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
