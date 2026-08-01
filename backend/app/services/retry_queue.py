"""Retry queue / dead-letter queue service.

Generic across job types -- any operation that can fail per unit of work
(email ingestion, AI triage, ...) enqueues a failure here via
:meth:`RetryQueueService.enqueue_failure` instead of growing its own bespoke
retry mechanism. The scheduled ``process_retry_queue`` job (see
``app/scheduler.py``) is the only thing that drains this queue, dispatching
by ``job_type`` through the registry in ``app/infra/job_registry.py``.

Backoff is exponential with a cap: 30s, 60s, 120s, 240s, ... up to 1 hour.
A job that exhausts ``max_attempts`` moves to ``status="dead_letter"`` and is
no longer retried automatically -- see the module docstring on
``app/infra/models/failed_job.py`` for the full state machine.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from app.config.logging import get_logger
from app.core.time import utcnow
from app.infra.models.failed_job import FailedJob
from app.infra.repositories.failed_job import FailedJobRepository

logger = get_logger(__name__)

_BACKOFF_BASE_SECONDS = 30
_BACKOFF_MAX_SECONDS = 3600
_DEFAULT_MAX_ATTEMPTS = 5


def _next_backoff(attempt_count: int) -> datetime:
    delay = min(
        _BACKOFF_BASE_SECONDS * (2 ** max(attempt_count - 1, 0)), _BACKOFF_MAX_SECONDS
    )
    return utcnow() + timedelta(seconds=delay)


class RetryQueueService:
    """Enqueues, drains, and inspects the retry / dead-letter queue."""

    def __init__(self, repository: FailedJobRepository) -> None:
        self._repo = repository

    async def enqueue_failure(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        job_type: str,
        payload: dict[str, Any],
        error: BaseException | str,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        next_attempt_at: datetime | None = None,
    ) -> FailedJob:
        """Record a unit of work for later (re)processing.

        ``next_attempt_at`` defaults to the standard exponential backoff,
        but callers scheduling a *deferral* rather than a failure (e.g.
        notification delivery suppressed during quiet hours -- see
        ``app/services/notification_dispatch.py``) can pass an explicit
        time instead.
        """
        job = FailedJob(
            tenant_id=tenant_id,
            user_id=user_id,
            job_type=job_type,
            payload=payload,
            error_message=str(error)[:2000],
            attempt_count=1,
            max_attempts=max_attempts,
            status="pending",
            next_attempt_at=next_attempt_at
            if next_attempt_at is not None
            else _next_backoff(1),
        )
        job = await self._repo.add(job)
        logger.warning(
            "job_enqueued_for_retry",
            job_type=job_type,
            job_id=str(job.id),
            error=str(error)[:500],
        )
        return job

    async def list_due(self, *, limit: int = 100) -> Sequence[FailedJob]:
        """Return pending jobs ready for another attempt."""
        return await self._repo.list_due(now=utcnow(), limit=limit)

    async def record_success(self, job: FailedJob) -> None:
        """Mark a retried job resolved -- it will not be retried again."""
        await self._repo.update_fields(job.id, status="resolved", resolved_at=utcnow())
        logger.info("retry_job_resolved", job_type=job.job_type, job_id=str(job.id))

    async def record_failure(self, job: FailedJob, error: BaseException | str) -> None:
        """Record another failed attempt: reschedule, or dead-letter if exhausted."""
        attempt_count = job.attempt_count + 1
        error_message = str(error)[:2000]
        if attempt_count >= job.max_attempts:
            await self._repo.update_fields(
                job.id,
                status="dead_letter",
                attempt_count=attempt_count,
                error_message=error_message,
            )
            logger.error(
                "retry_job_dead_lettered",
                job_type=job.job_type,
                job_id=str(job.id),
                attempts=attempt_count,
            )
        else:
            await self._repo.update_fields(
                job.id,
                attempt_count=attempt_count,
                error_message=error_message,
                next_attempt_at=_next_backoff(attempt_count),
            )
            logger.warning(
                "retry_job_reattempt_scheduled",
                job_type=job.job_type,
                job_id=str(job.id),
                attempts=attempt_count,
            )

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[FailedJob]:
        """Return a tenant's failed jobs, optionally filtered by status."""
        return await self._repo.list_by_tenant(
            tenant_id, status=status, limit=limit, offset=offset
        )

    async def count_pending(self) -> int:
        """Return the total number of jobs awaiting retry, all tenants."""
        return await self._repo.count_by_status("pending")

    async def count_dead_letter(self) -> int:
        """Return the total number of dead-lettered jobs, all tenants."""
        return await self._repo.count_by_status("dead_letter")

    async def purge_resolved_older_than(self, *, retention_days: int) -> int:
        """Hard-delete resolved jobs older than the retention window.

        Returns:
            The number of rows purged.
        """
        cutoff = utcnow() - timedelta(days=retention_days)
        stale = await self._repo.list_resolved_older_than(cutoff=cutoff)
        for job in stale:
            await self._repo.delete(job.id)
        return len(stale)
