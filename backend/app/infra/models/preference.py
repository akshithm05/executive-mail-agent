"""Preference ORM model.

A flexible per-user key/value settings store, rather than one column per
setting -- new preferences ship without a migration.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import (
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Preference(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A single named preference/setting for a user."""

    __tablename__ = "preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_preferences_user_id_key"),
        Index("ix_preferences_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Preference id={self.id!s} key={self.key!r}>"
