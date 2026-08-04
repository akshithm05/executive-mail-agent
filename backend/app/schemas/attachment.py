"""Attachment request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentCreate(BaseModel):
    """Fields required to create attachment metadata."""

    tenant_id: uuid.UUID
    email_id: uuid.UUID
    # No max_length: Gmail's real attachment ids are opaque tokens that can
    # run well past 255 characters -- matches the Attachment model's Text
    # column (app/infra/models/attachment.py).
    gmail_attachment_id: str
    filename: str = Field(max_length=255)
    mime_type: str = Field(max_length=255)
    size_bytes: int = Field(default=0, ge=0)
    storage_uri: str | None = Field(default=None, max_length=2048)


class AttachmentUpdate(BaseModel):
    """Mutable fields on an attachment; omitted fields are left unchanged."""

    storage_uri: str | None = None


class AttachmentRead(BaseModel):
    """Full attachment representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email_id: uuid.UUID
    gmail_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    storage_uri: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
