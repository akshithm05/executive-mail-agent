"""Retry/dead-letter queue, email polling watermark, weekly digest type.

Revision ID: 0009_scheduled_jobs
Revises: 0008_email_triage_fields
Create Date: 2026-07-31 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_scheduled_jobs"
down_revision: str | None = "0008_email_triage_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FAILED_JOB_STATUSES = ("pending", "dead_letter", "resolved")
_OLD_SUMMARY_TYPES = ("email", "thread", "daily_digest")
_NEW_SUMMARY_TYPES = (*_OLD_SUMMARY_TYPES, "weekly_digest")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    """Add the failed_jobs table, a Gmail-poll watermark, and weekly_digest."""
    op.create_table(
        "failed_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"status IN {_FAILED_JOB_STATUSES}", name="ck_failed_jobs_status"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_failed_jobs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_failed_jobs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failed_jobs")),
    )
    op.create_index("ix_failed_jobs_tenant_id", "failed_jobs", ["tenant_id"])
    op.create_index("ix_failed_jobs_job_type", "failed_jobs", ["job_type"])
    op.create_index(
        "ix_failed_jobs_status_next_attempt_at",
        "failed_jobs",
        ["status", "next_attempt_at"],
    )

    op.add_column(
        "google_credentials",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint("ck_summaries_summary_type", "summaries", type_="check")
    op.create_check_constraint(
        "ck_summaries_summary_type", "summaries", f"summary_type IN {_NEW_SUMMARY_TYPES}"
    )


def downgrade() -> None:
    """Reverse the retry-queue table, poll watermark, and weekly_digest type."""
    op.drop_constraint("ck_summaries_summary_type", "summaries", type_="check")
    op.create_check_constraint(
        "ck_summaries_summary_type", "summaries", f"summary_type IN {_OLD_SUMMARY_TYPES}"
    )

    op.drop_column("google_credentials", "last_polled_at")

    op.drop_index("ix_failed_jobs_status_next_attempt_at", table_name="failed_jobs")
    op.drop_index("ix_failed_jobs_job_type", table_name="failed_jobs")
    op.drop_index("ix_failed_jobs_tenant_id", table_name="failed_jobs")
    op.drop_table("failed_jobs")
