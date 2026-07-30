"""Task ORM model."""

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
    from app.infra.models.ai_history import AIHistory
    from app.infra.models.email import Email

STATUSES = ("pending", "in_progress", "completed", "cancelled")
PRIORITIES = ("low", "medium", "high", "urgent")
CREATED_BY_VALUES = ("user", "ai")


class Task(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """An action item, either user-created or AI-extracted from an email."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_id_status", "user_id", "status"),
        Index("ix_tasks_user_id_due_at", "user_id", "due_at"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_tasks_status"),
        CheckConstraint(f"priority IN {PRIORITIES}", name="ck_tasks_priority"),
        CheckConstraint(
            f"created_by IN {CREATED_BY_VALUES}", name="ck_tasks_created_by"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: a task outlives the email it was extracted from.
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    # SET NULL, not CASCADE: if the blocking task is deleted, this task
    # becomes unblocked rather than being deleted itself.
    depends_on_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    email: Mapped[Email | None] = relationship(back_populates="tasks")
    ai_history_entries: Mapped[list[AIHistory]] = relationship(back_populates="task")
    # Self-referential: this task is blocked by (at most) one other task,
    # and can itself block any number of others.
    depends_on: Mapped[Task | None] = relationship(
        remote_side="Task.id",
        foreign_keys="Task.depends_on_task_id",
        back_populates="blocking",
    )
    blocking: Mapped[list[Task]] = relationship(
        foreign_keys="Task.depends_on_task_id", back_populates="depends_on"
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Task id={self.id!s} status={self.status!r}>"
