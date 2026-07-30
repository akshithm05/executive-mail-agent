"""Label request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LabelCreate(BaseModel):
    """Fields required to create a label."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    name: str = Field(max_length=255)
    gmail_label_id: str | None = Field(default=None, max_length=255)
    type: str = Field(default="user", max_length=32)
    color: str | None = Field(default=None, max_length=32)


class LabelUpdate(BaseModel):
    """Mutable fields on a label; omitted fields are left unchanged."""

    name: str | None = Field(default=None, max_length=255)
    color: str | None = None


class LabelRead(BaseModel):
    """Full label representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    gmail_label_id: str | None
    name: str
    type: str
    color: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class EmailLabelRead(BaseModel):
    """An email-label assignment, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_id: uuid.UUID
    label_id: uuid.UUID
    created_at: datetime
