"""Multi-channel notification service: channel configs, push devices, rules,
quiet hours, and per-delivery audit log.

Revision ID: 0010_notification_channels
Revises: 0009_scheduled_jobs
Create Date: 2026-07-31 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_notification_channels"
down_revision: str | None = "0009_scheduled_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLETON_CHANNEL_TYPES = ("slack", "discord", "telegram", "whatsapp", "email", "webhook")
_PUSH_DEVICE_PLATFORMS = ("web", "ios", "android")
_NOTIFICATION_DELIVERY_STATUSES = (
    "sent",
    "failed",
    "deferred",
    "skipped_rule",
    "skipped_quiet_hours",
)


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
    """Add the notification-channel-config, push-device, rule, quiet-hours, and delivery-log tables."""
    op.create_table(
        "notification_channel_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_ciphertext", sa.Text(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"channel_type IN {_SINGLETON_CHANNEL_TYPES}",
            name="ck_notification_channel_configs_channel_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notification_channel_configs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_channel_configs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_channel_configs")),
        sa.UniqueConstraint(
            "user_id",
            "channel_type",
            name="uq_notification_channel_configs_user_channel",
        ),
    )
    op.create_index(
        "ix_notification_channel_configs_user_id",
        "notification_channel_configs",
        ["user_id"],
    )

    op.create_table(
        "push_devices",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"platform IN {_PUSH_DEVICE_PLATFORMS}", name="ck_push_devices_platform"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_push_devices_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_push_devices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_devices")),
    )
    op.create_index(
        "ix_push_devices_user_id_is_active", "push_devices", ["user_id", "is_active"]
    )

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "only_important", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("notification_types", sa.JSON(), nullable=True),
        sa.Column("keyword", sa.String(length=255), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notification_rules_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_rules_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_rules")),
    )
    op.create_index(
        "ix_notification_rules_user_id_is_enabled",
        "notification_rules",
        ["user_id", "is_enabled"],
    )

    op.create_table(
        "notification_quiet_hours",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("start_time", sa.Time(), nullable=False, server_default="22:00:00"),
        sa.Column("end_time", sa.Time(), nullable=False, server_default="07:00:00"),
        sa.Column(
            "timezone", sa.String(length=64), nullable=False, server_default="UTC"
        ),
        sa.Column(
            "allow_urgent_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notification_quiet_hours_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_quiet_hours_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_quiet_hours")),
        sa.UniqueConstraint("user_id", name="uq_notification_quiet_hours_user_id"),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("notification_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"status IN {_NOTIFICATION_DELIVERY_STATUSES}",
            name="ck_notification_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notification_deliveries_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name=op.f("fk_notification_deliveries_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
    )
    op.create_index(
        "ix_notification_deliveries_notification_id",
        "notification_deliveries",
        ["notification_id"],
    )


def downgrade() -> None:
    """Drop the notification-channel-config, push-device, rule, quiet-hours, and delivery-log tables."""
    op.drop_index(
        "ix_notification_deliveries_notification_id",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")

    op.drop_table("notification_quiet_hours")

    op.drop_index(
        "ix_notification_rules_user_id_is_enabled", table_name="notification_rules"
    )
    op.drop_table("notification_rules")

    op.drop_index("ix_push_devices_user_id_is_active", table_name="push_devices")
    op.drop_table("push_devices")

    op.drop_index(
        "ix_notification_channel_configs_user_id",
        table_name="notification_channel_configs",
    )
    op.drop_table("notification_channel_configs")
