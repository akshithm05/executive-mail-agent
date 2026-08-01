"""NotificationQuietHours ORM model.

One row per user (singleton, enforced by the unique constraint on
``user_id``): a local-time window during which external-channel delivery is
deferred rather than sent immediately. The in-app :class:`~app.infra.models.
notification.Notification` row is unaffected -- quiet hours only delay the
Slack/Discord/Telegram/WhatsApp/push/email/webhook fan-out (see
``app/services/quiet_hours.py`` for the window evaluator and
``app/services/notification_dispatch.py`` for how a deferral is scheduled).
"""

from __future__ import annotations

import uuid
from datetime import time as time_

from sqlalchemy import Boolean, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationQuietHours(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base
):
    """A user's quiet-hours configuration."""

    __tablename__ = "notification_quiet_hours"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Local time-of-day window [start_time, end_time). `start_time >
    # end_time` is a valid overnight window (e.g. 22:00 -> 07:00), evaluated
    # by wrapping past midnight -- see `app/services/quiet_hours.py`.
    start_time: Mapped[time_] = mapped_column(
        Time, nullable=False, default=time_(22, 0)
    )
    end_time: Mapped[time_] = mapped_column(Time, nullable=False, default=time_(7, 0))
    # IANA timezone name (e.g. "America/New_York"); the window above is
    # interpreted in this timezone, not UTC.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # When true, a notification the dispatch service considers "urgent"
    # (see its docstring) is delivered immediately even during quiet hours,
    # instead of being deferred until the window ends.
    allow_urgent_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<NotificationQuietHours user_id={self.user_id!s} "
            f"is_enabled={self.is_enabled!r}>"
        )
