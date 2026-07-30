"""Notification request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    """Fields required to create a notification."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    type: str = Field(max_length=64)
    title: str = Field(max_length=255)
    body: str = ""
    related_entity_type: str | None = Field(default=None, max_length=64)
    related_entity_id: uuid.UUID | None = None


class NotificationRead(BaseModel):
    """Full notification representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    is_read: bool
    read_at: datetime | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
