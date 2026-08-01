"""PromptLog repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
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

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Hard-delete prompt logs created before ``cutoff``.

        Used by the scheduled cleanup sweep -- prompt/response logs are pure
        observability data with unbounded growth (one row per LLM call);
        unlike business data they carry no soft-delete/audit requirement
        past their retention window. ``cutoff`` is normalized to naive UTC
        (see ``app/core/time.py``) since ``created_at`` is a naive column.
        """
        stmt = delete(PromptLog).where(PromptLog.created_at < as_naive_utc(cutoff))
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
