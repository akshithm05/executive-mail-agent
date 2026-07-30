"""Task CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.infra.models.task import Task
from app.infra.repositories.task import TaskRepository
from app.services.crud import CRUDService


class TaskService(CRUDService[Task]):
    """CRUD operations for tasks, plus status-transition helpers."""

    def __init__(self, repository: TaskRepository) -> None:
        super().__init__(repository)
        self._repo: TaskRepository = repository

    async def list_by_status(
        self, user_id: uuid.UUID, status: str, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Task]:
        """Return a user's tasks in a given status, soonest-due first."""
        return await self._repo.list_by_status(
            user_id, status, limit=limit, offset=offset
        )

    async def complete(self, task_id: uuid.UUID) -> Task | None:
        """Mark a task completed and stamp its completion time."""
        return await self.update(
            task_id, status="completed", completed_at=datetime.now(UTC)
        )
