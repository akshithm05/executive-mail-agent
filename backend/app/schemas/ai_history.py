"""AIHistory request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIHistoryCreate(BaseModel):
    """Fields required to create an AI history entry."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    action_type: str = Field(max_length=64)
    input_summary: str | None = None
    output_summary: str | None = None
    model_name: str = Field(default="", max_length=128)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class AIHistoryRead(BaseModel):
    """Full AI history entry representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None
    task_id: uuid.UUID | None
    action_type: str
    input_summary: str | None
    output_summary: str | None
    model_name: str
    extra_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
