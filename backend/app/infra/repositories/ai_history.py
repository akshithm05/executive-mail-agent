"""AIHistory repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.ai_history import AIHistory
from app.infra.repositories.base import SoftDeleteRepository


class AIHistoryRepository(SoftDeleteRepository[AIHistory]):
    """Persistence operations for AI action history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AIHistory)

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AIHistory]:
        """Return a user's AI history, most recent first."""
        stmt = (
            select(AIHistory)
            .where(AIHistory.user_id == user_id, AIHistory.deleted_at.is_(None))
            .order_by(AIHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
