"""Summary repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.summary import Summary
from app.infra.repositories.base import SoftDeleteRepository


class SummaryRepository(SoftDeleteRepository[Summary]):
    """Persistence operations for AI-generated summaries."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Summary)

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[Summary]:
        """Return all summaries generated for a given email."""
        stmt = select(Summary).where(
            Summary.email_id == email_id, Summary.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
