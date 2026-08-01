"""Google OAuth credential ORM model.

Stores the tokens issued by Google for a user's Gmail access. Both token
columns hold ciphertext produced by :class:`app.core.crypto.TokenCipher` --
never plaintext -- so a database leak alone does not expose mailbox access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GoogleCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encrypted Google OAuth tokens for a single user (1:1)."""

    __tablename__ = "google_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    token_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Bearer"
    )
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    needs_reauth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # High-water mark for the scheduled Gmail-polling job (see
    # app/services/email_polling_service.py) -- messages received after this
    # timestamp are fetched on the next poll. Null means "never polled";
    # the poller bounds its first search window instead of importing a
    # mailbox's entire history.
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return (
            f"<GoogleCredential user_id={self.user_id!s} "
            f"needs_reauth={self.needs_reauth!r}>"
        )
