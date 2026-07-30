"""PromptLog repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.prompt_log import PromptLog
from app.infra.repositories.base import SoftDeleteRepository


class PromptLogRepository(SoftDeleteRepository[PromptLog]):
    """Persistence operations for LLM prompt/response logs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PromptLog)

    async def list_by_ai_history(self, ai_history_id: uuid.UUID) -> Sequence[PromptLog]:
        """Return all prompt logs backing a given AI history entry."""
        stmt = select(PromptLog).where(
            PromptLog.ai_history_id == ai_history_id, PromptLog.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
