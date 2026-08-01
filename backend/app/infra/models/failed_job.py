"""FailedJob ORM model -- the retry queue and dead-letter queue.

A single table backs both concepts: a row with ``status="pending"`` is a
retry-queue entry (picked up by the scheduled ``process_retry_queue`` job in
``app/scheduler.py`` once ``next_attempt_at`` has passed); a row that
exhausts ``max_attempts`` flips to ``status="dead_letter"`` and is no longer
retried automatically -- it stays queryable (see
``GET /api/v1/system/failed-jobs``) for manual inspection/replay. A row that
eventually succeeds flips to ``status="resolved"`` and is purged by the
cleanup sweep after a retention window.

``job_type`` + ``payload`` (JSON) describe the unit of work generically --
see ``app/infra/job_registry.py`` for the mapping from ``job_type`` back to
an async handler -- so any future failure-prone operation can reuse this one
table instead of growing a bespoke retry mechanism per feature.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

FAILED_JOB_STATUSES = ("pending", "dead_letter", "resolved")


class FailedJob(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A unit of work that failed at least once, tracked for retry."""

    __tablename__ = "failed_jobs"
    __table_args__ = (
        Index("ix_failed_jobs_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_failed_jobs_job_type", "job_type"),
        CheckConstraint(
            f"status IN {FAILED_JOB_STATUSES}", name="ck_failed_jobs_status"
        ),
    )

    # SET NULL, not CASCADE: a failed job is a record of what went wrong and
    # should survive the user row it was about (e.g. account deletion)
    # long enough to be reviewed, rather than silently disappearing.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<FailedJob id={self.id!s} job_type={self.job_type!r} "
            f"status={self.status!r} attempt={self.attempt_count}>"
        )
