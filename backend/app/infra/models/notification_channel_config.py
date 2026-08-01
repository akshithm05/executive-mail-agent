"""NotificationChannelConfig ORM model.

Per-user, per-channel delivery configuration for the "singleton" channels --
channels a user configures exactly one destination for (a Slack webhook URL,
a Telegram chat id, ...), as opposed to the multi-device push channels (see
``app/infra/models/push_device.py``).

``config_ciphertext`` holds the whole channel-specific config dict as one
Fernet-encrypted JSON blob (via :class:`app.core.crypto.TokenCipher`) rather
than per-field encryption -- these configs are small and read as a unit, so
one ciphertext column is simpler than N encrypted columns, while still
guaranteeing no webhook URL, bot chat id, or phone number sits in the
database in plaintext.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

# The "singleton" channels: exactly one destination per user. Desktop and
# mobile_push are multi-device and live in ``PushDevice`` instead -- they are
# deliberately excluded here.
SINGLETON_CHANNEL_TYPES = (
    "slack",
    "discord",
    "telegram",
    "whatsapp",
    "email",
    "webhook",
)


class NotificationChannelConfig(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base
):
    """One user's delivery configuration for one singleton notification channel."""

    __tablename__ = "notification_channel_configs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "channel_type",
            name="uq_notification_channel_configs_user_channel",
        ),
        Index("ix_notification_channel_configs_user_id", "user_id"),
        CheckConstraint(
            f"channel_type IN {SINGLETON_CHANNEL_TYPES}",
            name="ck_notification_channel_configs_channel_type",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<NotificationChannelConfig user_id={self.user_id!s} "
            f"channel_type={self.channel_type!r} is_enabled={self.is_enabled!r}>"
        )
