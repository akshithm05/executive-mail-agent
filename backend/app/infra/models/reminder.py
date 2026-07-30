"""Reminder ORM model.

A scheduled, one-time nudge for a task or calendar event -- created
automatically when the email-triage graph extracts a task with a deadline
or suggests a calendar event (see ``app/agents/graph.py``), and fired by a
periodic APScheduler job (see ``app/scheduler.py``) that polls for reminders
whose ``remind_at`` has passed and converts them into a
:class:`~app.infra.models.notification.Notification`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base
from app.infra.db.mixins import (
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.infra.models.calendar_event import CalendarEvent
    from app.infra.models.task import Task

STATUSES = ("pending", "sent", "cancelled")


class Reminder(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A scheduled reminder for a task's deadline or an upcoming calendar event."""

    __tablename__ = "reminders"
    __table_args__ = (
        Index(
            "ix_reminders_user_id_status_remind_at", "user_id", "status", "remind_at"
        ),
        Index("ix_reminders_task_id", "task_id"),
        Index("ix_reminders_calendar_event_id", "calendar_event_id"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_reminders_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    calendar_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True
    )
    remind_at: Mapped[datetime] = mapped_column(nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    task: Mapped[Task | None] = relationship()
    calendar_event: Mapped[CalendarEvent | None] = relationship()

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Reminder id={self.id!s} status={self.status!r}>"
