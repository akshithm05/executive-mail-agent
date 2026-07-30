"""Email repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.email import Email
from app.infra.repositories.base import SoftDeleteRepository


class EmailRepository(SoftDeleteRepository[Email]):
    """Persistence operations for emails."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Email)

    async def get_by_gmail_message_id(
        self, user_id: uuid.UUID, gmail_message_id: str
    ) -> Email | None:
        """Return the email with the given Gmail message id for this user."""
        stmt = select(Email).where(
            Email.user_id == user_id,
            Email.gmail_message_id == gmail_message_id,
            Email.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_thread(
        self, user_id: uuid.UUID, gmail_thread_id: str
    ) -> Sequence[Email]:
        """Return all emails in a thread, oldest first."""
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.gmail_thread_id == gmail_thread_id,
                Email.deleted_at.is_(None),
            )
            .order_by(Email.received_at)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_unread(
        self, user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Email]:
        """Return unread emails for a user, most recent first."""
        stmt = (
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.is_read.is_(False),
                Email.deleted_at.is_(None),
            )
            .order_by(Email.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
