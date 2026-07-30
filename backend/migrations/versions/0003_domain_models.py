"""Phase 3 domain models.

Emails, attachments, labels, tasks, calendar events, draft replies, AI
history, prompt logs, summaries, preferences, memories, notifications, and
audit logs.

Revision ID: 0003_domain_models
Revises: 0002_google_auth
Create Date: 2026-07-30 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_domain_models"
down_revision: str | None = "0002_google_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp_columns() -> list[sa.Column]:
    """Return the ``created_at``/``updated_at`` columns shared by every table."""
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
    """Create all Phase 3 domain tables."""
    op.create_table(
        "emails",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("snippet", sa.String(length=1024), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("to_addresses", sa.Text(), nullable=False),
        sa.Column("cc_addresses", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("is_starred", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_emails_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_emails_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emails")),
        sa.UniqueConstraint(
            "user_id", "gmail_message_id", name="uq_emails_user_id_gmail_message_id"
        ),
    )
    op.create_index("ix_emails_tenant_id", "emails", ["tenant_id"])
    op.create_index("ix_emails_deleted_at", "emails", ["deleted_at"])
    op.create_index(
        "ix_emails_user_id_received_at", "emails", ["user_id", "received_at"]
    )
    op.create_index(
        "ix_emails_user_id_gmail_thread_id", "emails", ["user_id", "gmail_thread_id"]
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gmail_attachment_id", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.String(length=2048), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_attachments_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_attachments_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint(
            "email_id",
            "gmail_attachment_id",
            name="uq_attachments_email_id_gmail_attachment_id",
        ),
    )
    op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])
    op.create_index("ix_attachments_deleted_at", "attachments", ["deleted_at"])
    op.create_index("ix_attachments_email_id", "attachments", ["email_id"])

    op.create_table(
        "labels",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gmail_label_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_labels_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_labels_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
        sa.UniqueConstraint("user_id", "name", name="uq_labels_user_id_name"),
    )
    op.create_index("ix_labels_tenant_id", "labels", ["tenant_id"])
    op.create_index("ix_labels_deleted_at", "labels", ["deleted_at"])
    op.create_index("ix_labels_user_id", "labels", ["user_id"])

    op.create_table(
        "email_labels",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("label_id", sa.Uuid(as_uuid=True), nullable=False),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_email_labels_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
            name=op.f("fk_email_labels_label_id_labels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_labels")),
        sa.UniqueConstraint(
            "email_id", "label_id", name="uq_email_labels_email_id_label_id"
        ),
    )
    op.create_index("ix_email_labels_label_id", "email_labels", ["label_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')", name="ck_tasks_priority"
        ),
        sa.CheckConstraint("created_by IN ('user', 'ai')", name="ck_tasks_created_by"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tasks_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tasks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_tasks_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_deleted_at", "tasks", ["deleted_at"])
    op.create_index("ix_tasks_user_id_status", "tasks", ["user_id", "status"])
    op.create_index("ix_tasks_user_id_due_at", "tasks", ["user_id", "due_at"])

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("google_event_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attendees", sa.JSON(), nullable=False),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "status IN ('confirmed', 'tentative', 'cancelled')",
            name="ck_calendar_events_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_calendar_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_calendar_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_calendar_events_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_events")),
        sa.UniqueConstraint(
            "user_id",
            "google_event_id",
            name="uq_calendar_events_user_id_google_event_id",
        ),
    )
    op.create_index("ix_calendar_events_tenant_id", "calendar_events", ["tenant_id"])
    op.create_index("ix_calendar_events_deleted_at", "calendar_events", ["deleted_at"])
    op.create_index(
        "ix_calendar_events_user_id_start_at",
        "calendar_events",
        ["user_id", "start_at"],
    )

    op.create_table(
        "draft_replies",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_by", sa.String(length=16), nullable=False),
        sa.Column("gmail_draft_id", sa.String(length=255), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'sent', 'discarded')",
            name="ck_draft_replies_status",
        ),
        sa.CheckConstraint(
            "generated_by IN ('ai', 'user')", name="ck_draft_replies_generated_by"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_draft_replies_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_draft_replies_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_draft_replies_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_replies")),
    )
    op.create_index("ix_draft_replies_tenant_id", "draft_replies", ["tenant_id"])
    op.create_index("ix_draft_replies_deleted_at", "draft_replies", ["deleted_at"])
    op.create_index("ix_draft_replies_email_id", "draft_replies", ["email_id"])
    op.create_index(
        "ix_draft_replies_user_id_status", "draft_replies", ["user_id", "status"]
    )

    op.create_table(
        "ai_history",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_history_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ai_history_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_ai_history_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_ai_history_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_history")),
    )
    op.create_index("ix_ai_history_tenant_id", "ai_history", ["tenant_id"])
    op.create_index("ix_ai_history_deleted_at", "ai_history", ["deleted_at"])
    op.create_index(
        "ix_ai_history_user_id_created_at", "ai_history", ["user_id", "created_at"]
    )
    op.create_index("ix_ai_history_email_id", "ai_history", ["email_id"])
    op.create_index("ix_ai_history_task_id", "ai_history", ["task_id"])

    op.create_table(
        "prompt_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("ai_history_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "status IN ('success', 'error')", name="ck_prompt_logs_status"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_prompt_logs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_prompt_logs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ai_history_id"],
            ["ai_history.id"],
            name=op.f("fk_prompt_logs_ai_history_id_ai_history"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_logs")),
    )
    op.create_index("ix_prompt_logs_tenant_id", "prompt_logs", ["tenant_id"])
    op.create_index("ix_prompt_logs_deleted_at", "prompt_logs", ["deleted_at"])
    op.create_index("ix_prompt_logs_created_at", "prompt_logs", ["created_at"])
    op.create_index("ix_prompt_logs_ai_history_id", "prompt_logs", ["ai_history_id"])
    op.create_index("ix_prompt_logs_user_id", "prompt_logs", ["user_id"])

    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("summary_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "summary_type IN ('email', 'thread', 'daily_digest')",
            name="ck_summaries_summary_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_summaries_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_summaries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"],
            ["emails.id"],
            name=op.f("fk_summaries_email_id_emails"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summaries")),
    )
    op.create_index("ix_summaries_tenant_id", "summaries", ["tenant_id"])
    op.create_index("ix_summaries_deleted_at", "summaries", ["deleted_at"])
    op.create_index(
        "ix_summaries_user_id_created_at", "summaries", ["user_id", "created_at"]
    )
    op.create_index("ix_summaries_email_id", "summaries", ["email_id"])

    op.create_table(
        "preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_preferences_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preferences")),
        sa.UniqueConstraint("user_id", "key", name="uq_preferences_user_id_key"),
    )
    op.create_index("ix_preferences_tenant_id", "preferences", ["tenant_id"])
    op.create_index("ix_preferences_deleted_at", "preferences", ["deleted_at"])
    op.create_index("ix_preferences_user_id", "preferences", ["user_id"])

    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_email_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.CheckConstraint(
            "memory_type IN "
            "('fact', 'preference_inference', 'relationship', 'context')",
            name="ck_memories_memory_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_memories_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_email_id"],
            ["emails.id"],
            name=op.f("fk_memories_source_email_id_emails"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index("ix_memories_tenant_id", "memories", ["tenant_id"])
    op.create_index("ix_memories_deleted_at", "memories", ["deleted_at"])
    op.create_index(
        "ix_memories_user_id_memory_type", "memories", ["user_id", "memory_type"]
    )
    op.create_index("ix_memories_source_email_id", "memories", ["source_email_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("related_entity_type", sa.String(length=64), nullable=True),
        sa.Column("related_entity_id", sa.Uuid(as_uuid=True), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notifications_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_deleted_at", "notifications", ["deleted_at"])
    op.create_index(
        "ix_notifications_user_id_is_read", "notifications", ["user_id", "is_read"]
    )
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        _soft_delete_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_logs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_deleted_at", "audit_logs", ["deleted_at"])
    op.create_index(
        "ix_audit_logs_user_id_created_at", "audit_logs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_entity_type_entity_id",
        "audit_logs",
        ["entity_type", "entity_id"],
    )


def downgrade() -> None:
    """Drop all Phase 3 domain tables, in reverse dependency order."""
    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("memories")
    op.drop_table("preferences")
    op.drop_table("summaries")
    op.drop_table("prompt_logs")
    op.drop_table("ai_history")
    op.drop_table("draft_replies")
    op.drop_table("calendar_events")
    op.drop_table("tasks")
    op.drop_table("email_labels")
    op.drop_table("labels")
    op.drop_table("attachments")
    op.drop_table("emails")
