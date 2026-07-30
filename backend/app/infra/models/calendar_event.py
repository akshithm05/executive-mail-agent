"""CalendarEvent ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base
from app.infra.db.mixins import (
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.infra.models.email import Email

STATUSES = ("confirmed", "tentative", "cancelled")


class CalendarEvent(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A calendar event, synced from Google Calendar or AI-suggested from an email."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "google_event_id",
            name="uq_calendar_events_user_id_google_event_id",
        ),
        Index("ix_calendar_events_user_id_start_at", "user_id", "start_at"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_calendar_events_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    # Nullable + unique-per-user: internally created/AI-suggested events have
    # no Google Calendar counterpart (yet); Postgres/SQLite both treat NULLs
    # as distinct under a unique constraint, so multiple such events coexist.
    google_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_at: Mapped[datetime] = mapped_column(nullable=False)
    end_at: Mapped[datetime] = mapped_column(nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    attendees: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # Null: never pushed to Google Calendar. Set (alongside google_event_id)
    # each time app.services.calendar_sync_service pushes this row.
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # SHA-256 of the syncable fields (title/description/location/start/end)
    # as of the last successful push. Re-sync is needed when this no longer
    # matches the row's current content -- a content hash rather than an
    # ``updated_at`` timestamp comparison, since ``updated_at`` is a
    # server-side ``onupdate=func.now()`` column whose precision (seconds,
    # on SQLite) isn't fine enough to reliably order against a
    # Python-side-set sync timestamp when both happen within the same
    # second.
    synced_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    email: Mapped[Email | None] = relationship(back_populates="calendar_events")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<CalendarEvent id={self.id!s} title={self.title!r}>"
