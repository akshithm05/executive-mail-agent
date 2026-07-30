"""AuditLog ORM model.

Security/compliance trail of significant actions (login, logout, data
access, deletions, settings changes).

``AuditLog`` carries :class:`~app.infra.db.mixins.SoftDeleteMixin` for
schema consistency with every other table in this system, but that is a
deliberate, narrow exception in practice: no repository or service method in
this codebase ever calls ``soft_delete`` on it (see
``app/services/audit_log.py``). An audit trail that the application itself
can hide defeats its purpose; the column exists, but nothing in the code
path uses it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import (
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AuditLog(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """An immutable record of one security/compliance-relevant action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<AuditLog id={self.id!s} action={self.action!r}>"
