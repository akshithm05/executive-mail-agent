"""PromptLog request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PromptLogStatus = Literal["success", "error"]


class PromptLogCreate(BaseModel):
    """Fields required to create a prompt log entry."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    ai_history_id: uuid.UUID | None = None
    provider: str = Field(max_length=64)
    model: str = Field(max_length=128)
    prompt_text: str
    response_text: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    status: PromptLogStatus = "success"
    error_message: str | None = None


class PromptLogRead(BaseModel):
    """Full prompt log representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    ai_history_id: uuid.UUID | None
    provider: str
    model: str
    prompt_text: str
    response_text: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
