"""Dashboard summary endpoint: powers the overview page in one request."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import TypeAdapter

from app.api.cache_utils import cache_key, cached
from app.api.deps import (
    CacheServiceDep,
    CurrentUserDep,
    DashboardServiceDep,
    SettingsDep,
)
from app.schemas.dashboard import DashboardSummaryResponse, PriorityHeatmapCell

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_SUMMARY_ADAPTER = TypeAdapter(DashboardSummaryResponse)


@router.get(
    "/summary", response_model=DashboardSummaryResponse, summary="Get dashboard summary"
)
async def get_dashboard_summary(
    user: CurrentUserDep,
    service: DashboardServiceDep,
    cache: CacheServiceDep,
    settings: SettingsDep,
) -> DashboardSummaryResponse:
    """Aggregate counts and chart data for the overview dashboard.

    Cached briefly (see ``RedisSettings.default_ttl_seconds``) -- this is
    the single most expensive, most frequently polled read in the API, and
    a few seconds of staleness is an acceptable tradeoff.
    """

    async def _compute() -> DashboardSummaryResponse:
        summary = await service.summarize(user.id)
        return DashboardSummaryResponse(
            total_emails=summary.total_emails,
            unread_emails=summary.unread_emails,
            urgent_emails=summary.urgent_emails,
            upcoming_deadlines=summary.upcoming_deadlines,
            pending_tasks=summary.pending_tasks,
            pending_drafts=summary.pending_drafts,
            unread_notifications=summary.unread_notifications,
            category_counts=summary.category_counts,
            priority_heatmap=[
                PriorityHeatmapCell(**cell) for cell in summary.priority_heatmap
            ],
        )

    return await cached(
        cache,
        cache_key("dashboard", "summary", user.id),
        adapter=_SUMMARY_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )
