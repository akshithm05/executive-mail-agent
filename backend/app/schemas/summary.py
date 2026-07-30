"""Summary request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SummaryType = Literal["email", "thread", "daily_digest"]


class SummaryCreate(BaseModel):
    """Fields required to create a summary."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None = None
    gmail_thread_id: str | None = Field(default=None, max_length=255)
    summary_type: SummaryType = "email"
    content: str
    model_name: str = Field(default="", max_length=128)


class SummaryRead(BaseModel):
    """Full summary representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None
    gmail_thread_id: str | None
    summary_type: str
    content: str
    model_name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
