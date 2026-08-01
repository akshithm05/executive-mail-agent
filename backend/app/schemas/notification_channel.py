"""Notification-channel-config request/response schemas.

``NotificationChannelConfigRead`` deliberately never includes the
decrypted (or even encrypted) config -- a user's Slack webhook URL,
Telegram chat id, etc. never leave the server once set, matching how
``GoogleCredential`` never round-trips its tokens either.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationChannelConfigUpdate(BaseModel):
    """Fields to create or update (upsert) a user's config for one channel."""

    config: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class NotificationChannelConfigRead(BaseModel):
    """A channel config's metadata -- never the underlying secret config."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_type: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
