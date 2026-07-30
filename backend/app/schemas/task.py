"""Task request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "in_progress", "completed", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskCreatedBy = Literal["user", "ai"]


class TaskCreate(BaseModel):
    """Fields required to create a task."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None = None
    title: str = Field(max_length=500)
    description: str | None = None
    status: TaskStatus = "pending"
    priority: TaskPriority = "medium"
    created_by: TaskCreatedBy = "user"
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    """Mutable fields on a task; omitted fields are left unchanged."""

    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None


class TaskRead(BaseModel):
    """Full task representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: str
    created_by: str
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
