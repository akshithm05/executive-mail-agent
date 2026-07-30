"""Preference request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PreferenceCreate(BaseModel):
    """Fields required to create a preference."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    key: str = Field(max_length=128)
    value: dict[str, Any] = Field(default_factory=dict)
    category: str | None = Field(default=None, max_length=64)


class PreferenceUpdate(BaseModel):
    """Mutable fields on a preference; omitted fields are left unchanged."""

    value: dict[str, Any] | None = None
    category: str | None = None


class PreferenceRead(BaseModel):
    """Full preference representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    key: str
    value: dict[str, Any]
    category: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
