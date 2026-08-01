"""Operational endpoints: Prometheus metrics and the dead-letter queue.

``/metrics`` is unauthenticated, per Prometheus scrape convention (the same
convention ``/health/*`` already follows in this codebase) -- it exposes
process-wide counters/gauges, never per-user data.

``/system/failed-jobs`` *is* authenticated and scoped to the current user's
tenant -- it exposes the retry-queue / dead-letter-queue entries (see
``app/infra/models/failed_job.py``) for manual inspection.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import CurrentUserDep, RetryQueueServiceDep
from app.infra.metrics import REGISTRY
from app.schemas.failed_job import FailedJobRead

router = APIRouter(tags=["system"])


@router.get("/metrics", summary="Prometheus metrics")
async def get_metrics() -> Response:
    """Expose process metrics in Prometheus text-exposition format."""
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get(
    "/system/failed-jobs",
    response_model=list[FailedJobRead],
    summary="List retry-queue / dead-letter-queue entries",
)
async def list_failed_jobs(
    user: CurrentUserDep,
    retry_queue: RetryQueueServiceDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[FailedJobRead]:
    """List the current user's tenant's failed jobs, optionally by status."""
    jobs = await retry_queue.list_by_tenant(
        user.tenant_id, status=status_filter, limit=limit, offset=offset
    )
    return [FailedJobRead.model_validate(job) for job in jobs]
