"""FailedJob repository -- the retry queue and dead-letter queue."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
from app.infra.models.failed_job import FailedJob
from app.infra.repositories.base import SQLAlchemyRepository


class FailedJobRepository(SQLAlchemyRepository[FailedJob]):
    """Persistence operations for the retry / dead-letter queue.

    Deliberately not a :class:`~app.infra.repositories.base.SoftDeleteRepository`
    -- these rows are already a terminal audit trail (pending, dead_letter, or
    resolved); the scheduled cleanup sweep hard-deletes resolved rows past a
    retention window instead of soft-deleting them.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FailedJob)

    async def list_due(self, *, now: datetime, limit: int = 100) -> Sequence[FailedJob]:
        """Return pending jobs whose ``next_attempt_at`` has passed.

        ``now`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``next_attempt_at`` is a naive column.
        """
        stmt = (
            select(FailedJob)
            .where(
                FailedJob.status == "pending",
                FailedJob.next_attempt_at <= as_naive_utc(now),
            )
            .order_by(FailedJob.next_attempt_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[FailedJob]:
        """Return a tenant's failed jobs, optionally filtered by status."""
        stmt = select(FailedJob).where(FailedJob.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(FailedJob.status == status)
        stmt = stmt.order_by(FailedJob.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_by_status(self, status: str) -> int:
        """Return the total number of failed jobs in a given status, all tenants."""
        stmt = select(func.count()).where(FailedJob.status == status)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_resolved_older_than(
        self, *, cutoff: datetime, limit: int = 500
    ) -> Sequence[FailedJob]:
        """Return resolved jobs last updated before ``cutoff`` (cleanup sweep).

        ``cutoff`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``updated_at`` is a naive column.
        """
        stmt = (
            select(FailedJob)
            .where(
                FailedJob.status == "resolved",
                FailedJob.updated_at < as_naive_utc(cutoff),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
