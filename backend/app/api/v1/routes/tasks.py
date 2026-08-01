"""Task endpoints: listing, editing, and completing tasks.

AI-extracted (see ``app/agents/graph.py``'s ``task_extraction`` node) and
user-created tasks share this same surface.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, TaskServiceDep
from app.core.exceptions import NotFoundError
from app.infra.models.task import Task
from app.schemas.task import TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _get_owned_task(
    task_id: uuid.UUID, user: CurrentUserDep, service: TaskServiceDep
) -> Task:
    """Fetch a task, scoped to the current user (404 if not theirs)."""
    task = await service.get(task_id)
    if task is None or task.user_id != user.id:
        raise NotFoundError("No task with this id was found.")
    return task


OwnedTaskDep = Annotated[Task, Depends(_get_owned_task)]


@router.get("", response_model=list[TaskRead], summary="List tasks")
async def list_tasks(
    user: CurrentUserDep,
    service: TaskServiceDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TaskRead]:
    """List the current user's tasks, optionally filtered by status."""
    tasks = await service.list_by_user(
        user.id, status=status_filter, limit=limit, offset=offset
    )
    return [TaskRead.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskRead, summary="Get one task")
async def get_task(task: OwnedTaskDep) -> TaskRead:
    """Fetch a single task by id."""
    return TaskRead.model_validate(task)


@router.patch("/{task_id}", response_model=TaskRead, summary="Edit a task")
async def edit_task(
    task: OwnedTaskDep, body: TaskUpdate, service: TaskServiceDep
) -> TaskRead:
    """Edit a task's mutable fields (title, description, status, priority, due date)."""
    fields = body.model_dump(exclude_unset=True)
    updated = await service.update(task.id, **fields) if fields else task
    return TaskRead.model_validate(cast(Task, updated))


@router.post("/{task_id}/complete", response_model=TaskRead, summary="Complete a task")
async def complete_task(task: OwnedTaskDep, service: TaskServiceDep) -> TaskRead:
    """Mark a task completed and stamp its completion time."""
    updated = await service.complete(task.id)
    return TaskRead.model_validate(cast(Task, updated))
