"""NotificationRule ORM model.

Custom, per-user filters deciding whether a given :class:`~app.infra.models.
notification.Notification` gets fanned out to external channels at all (the
in-app row is always created regardless -- these rules only gate the
Slack/Discord/Telegram/WhatsApp/push/email/webhook fan-out).

Semantics (see ``app/services/notification_rules.py`` for the evaluator):
a user with zero enabled rules gets everything delivered (no filtering,
today's default behavior). Once they add at least one enabled rule, a
notification is delivered only if it matches *at least one* of them. A rule
matches when *all* of its own non-null conditions hold.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A single custom notification-filtering rule for one user."""

    __tablename__ = "notification_rules"
    __table_args__ = (
        Index("ix_notification_rules_user_id_is_enabled", "user_id", "is_enabled"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Shorthand for "this notification concerns an email the triage agent
    # already flagged as important" -- true for `type in
    # ("high_priority_email", "draft_ready")`. See the evaluator for the
    # exact definition.
    only_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Allow-list of `Notification.type` values this rule matches, e.g.
    # `["reminder", "morning_digest"]`. Null/empty means "any type".
    notification_types: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Case-insensitive substring match against the notification's title or
    # body. Null means "no keyword condition".
    keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<NotificationRule id={self.id!s} name={self.name!r}>"
