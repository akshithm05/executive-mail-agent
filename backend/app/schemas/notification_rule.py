"""Custom notification-rule request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationRuleCreate(BaseModel):
    """Fields required to create a custom notification rule."""

    name: str = Field(max_length=128)
    is_enabled: bool = True
    only_important: bool = False
    notification_types: list[str] | None = None
    keyword: str | None = Field(default=None, max_length=255)


class NotificationRuleUpdate(BaseModel):
    """Mutable fields on a rule; omitted fields are left unchanged."""

    name: str | None = Field(default=None, max_length=128)
    is_enabled: bool | None = None
    only_important: bool | None = None
    notification_types: list[str] | None = None
    keyword: str | None = Field(default=None, max_length=255)


class NotificationRuleRead(BaseModel):
    """Full rule representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_enabled: bool
    only_important: bool
    notification_types: list[str] | None
    keyword: str | None
    created_at: datetime
    updated_at: datetime
