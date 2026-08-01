"""DraftReply repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time import as_naive_utc
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

    async def list_sent_between(
        self, user_id: uuid.UUID, *, since: datetime, limit: int = 20_000
    ) -> Sequence[DraftReply]:
        """Return sent replies since ``since``, with their email eagerly loaded.

        Feeds ``AnalyticsService.response_time_stats`` -- ``email`` is
        eagerly loaded (one extra join, not N+1 queries) since every caller
        needs ``email.received_at`` to compute elapsed response time.
        ``since`` is normalized to naive UTC (see ``app/core/time.py``).
        """
        stmt = (
            select(DraftReply)
            .where(
                DraftReply.user_id == user_id,
                DraftReply.deleted_at.is_(None),
                DraftReply.status == "sent",
                DraftReply.sent_at.is_not(None),
                DraftReply.sent_at >= as_naive_utc(since),
            )
            .options(selectinload(DraftReply.email))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
