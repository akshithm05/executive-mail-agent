"""PushDevice ORM model.

A registered push endpoint for the "desktop" (Web Push, one browser/device
subscription) or "mobile_push" (FCM, one app install) channels. Unlike the
singleton channels in :class:`~app.infra.models.notification_channel_config.
NotificationChannelConfig`, a user may have any number of push devices (one
per browser, one per phone) -- all active ones receive every dispatched push.

``token_ciphertext`` holds the platform-specific subscription payload as one
Fernet-encrypted JSON blob:

* ``platform="web"`` -- ``{"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}``
  (a browser ``PushSubscription``, JSON-serialized).
* ``platform="ios"`` / ``platform="android"`` -- ``{"fcm_token": ...}``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

PUSH_DEVICE_PLATFORMS = ("web", "ios", "android")


class PushDevice(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """One registered push endpoint (browser subscription or mobile token)."""

    __tablename__ = "push_devices"
    __table_args__ = (
        Index("ix_push_devices_user_id_is_active", "user_id", "is_active"),
        CheckConstraint(
            f"platform IN {PUSH_DEVICE_PLATFORMS}", name="ck_push_devices_platform"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<PushDevice id={self.id!s} platform={self.platform!r} "
            f"is_active={self.is_active!r}>"
        )
