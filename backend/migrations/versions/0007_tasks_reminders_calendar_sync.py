"""Task dependencies, reminders, and Google Calendar sync tracking.

Revision ID: 0007_scheduling_sync
Revises: 0006_draft_reply_engine
Create Date: 2026-07-30 03:00:00.000000

Note: the revision id is shorter than this file's descriptive name --
Alembic's own ``alembic_version.version_num`` column is a plain
``VARCHAR(32)``, and the full descriptive slug (34 chars) overflows it on
Postgres (SQLite silently ignores VARCHAR length limits, which is why this
was only caught booting against real Postgres, not in the SQLite-backed
test suite).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_scheduling_sync"
down_revision: str | None = "0006_draft_reply_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMINDER_STATUSES = ("pending", "sent", "cancelled")


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    ]


def _soft_delete_column() -> sa.Column:
    return sa.Column("deleted_at", sa.DateTime(), nullable=True)


def upgrade() -> None:
    """Add task dependencies, the reminders table, and calendar sync tracking."""
    op.add_column(
        "tasks",
        sa.Column("depends_on_task_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_depends_on_task_id_tasks",
        "tasks",
        "tasks",
        ["depends_on_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_tasks_depends_on_task_id", "tasks", ["depends_on_task_id"]
    )

    op.add_column(
        "calendar_events", sa.Column("last_synced_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "calendar_events",
        sa.Column("synced_hash", sa.String(length=64), nullable=True),
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("calendar_event_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("remind_at", sa.DateTime(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            f"status IN {_REMINDER_STATUSES}", name="ck_reminders_status"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_reminders_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reminders_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_reminders_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_event_id"],
            ["calendar_events.id"],
            name=op.f("fk_reminders_calendar_event_id_calendar_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminders")),
    )
    op.create_index("ix_reminders_tenant_id", "reminders", ["tenant_id"])
    op.create_index("ix_reminders_deleted_at", "reminders", ["deleted_at"])
    op.create_index(
        "ix_reminders_user_id_status_remind_at",
        "reminders",
        ["user_id", "status", "remind_at"],
    )
    op.create_index("ix_reminders_task_id", "reminders", ["task_id"])
    op.create_index(
        "ix_reminders_calendar_event_id", "reminders", ["calendar_event_id"]
    )


def downgrade() -> None:
    """Reverse task dependencies, the reminders table, and calendar sync tracking."""
    op.drop_table("reminders")
    op.drop_column("calendar_events", "synced_hash")
    op.drop_column("calendar_events", "last_synced_at")
    op.drop_index("ix_tasks_depends_on_task_id", table_name="tasks")
    op.drop_constraint(
        "fk_tasks_depends_on_task_id_tasks", "tasks", type_="foreignkey"
    )
    op.drop_column("tasks", "depends_on_task_id")
