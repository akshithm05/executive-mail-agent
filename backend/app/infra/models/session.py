"""First-party session ORM model.

Sessions back the application's own login state (as distinct from the Google
OAuth credential, which authorizes Gmail access). The cookie handed to the
browser contains a random opaque token; only its SHA-256 hash is stored here,
the same principle as password hashing -- a database leak does not yield a
usable session token.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Session(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A first-party login session for a user."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Session id={self.id!s} user_id={self.user_id!s}>"
