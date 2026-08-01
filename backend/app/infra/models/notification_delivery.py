"""NotificationDelivery ORM model.

An audit row for one attempted fan-out of one :class:`~app.infra.models.
notification.Notification` to one external channel. Multiple rows can exist
per (notification, channel) pair -- one per dispatch attempt (immediate,
deferred-for-quiet-hours, retried) -- forming a full delivery history rather
than a single mutable "last status" field.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

NOTIFICATION_DELIVERY_STATUSES = (
    "sent",
    "failed",
    "deferred",
    "skipped_rule",
    "skipped_quiet_hours",
)


class NotificationDelivery(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base
):
    """One delivery attempt of one notification to one channel."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_notification_id", "notification_id"),
        CheckConstraint(
            f"status IN {NOTIFICATION_DELIVERY_STATUSES}",
            name="ck_notification_deliveries_status",
        ),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<NotificationDelivery notification_id={self.notification_id!s} "
            f"channel_type={self.channel_type!r} status={self.status!r}>"
        )
