"""DraftReply repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.draft_reply import DraftReply
from app.infra.repositories.base import SoftDeleteRepository


class DraftReplyRepository(SoftDeleteRepository[DraftReply]):
    """Persistence operations for draft replies."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DraftReply)

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[DraftReply]:
        """Return all draft replies for a given email."""
        stmt = select(DraftReply).where(
            DraftReply.email_id == email_id, DraftReply.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[DraftReply]:
        """Return a user's draft replies, optionally filtered by status."""
        stmt = select(DraftReply).where(
            DraftReply.user_id == user_id, DraftReply.deleted_at.is_(None)
        )
        if status is not None:
            stmt = stmt.where(DraftReply.status == status)
        stmt = stmt.order_by(DraftReply.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()
