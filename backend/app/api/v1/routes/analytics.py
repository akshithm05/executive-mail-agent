"""Analytics endpoints: per-chart data, a combined report, and CSV/PDF export.

Every ranged endpoint takes its window in the unit its chart naturally uses
(``days`` for daily/response-time/task-completion charts, ``weeks`` for the
weekly chart, ``months`` for the monthly-trends chart) rather than forcing
every caller to convert -- an interactive dashboard fetches only the charts
currently on screen instead of always paying for the full report (see
``GET /analytics/report`` for the one-request combined payload CSV/PDF
export also renders).
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from pydantic import TypeAdapter

from app.api.cache_utils import cache_key, cached
from app.api.deps import (
    AnalyticsServiceDep,
    CacheServiceDep,
    CurrentUserDep,
    SettingsDep,
)
from app.core.exceptions import ValidationError
from app.schemas.analytics import (
    AnalyticsReportRead,
    CategoryCountRead,
    MonthlyTrendPointRead,
    PriorityBandCountRead,
    ResponseTimeStatsRead,
    TaskCompletionStatsRead,
    TaskPriorityBreakdownRead,
    TimeSeriesPointRead,
    UnreadAgeBandCountRead,
    UnreadSummaryRead,
)
from app.services.analytics import AnalyticsReport
from app.services.analytics_export import render_csv, render_pdf

router = APIRouter(prefix="/analytics", tags=["analytics"])

_POINT_LIST_ADAPTER = TypeAdapter(list[TimeSeriesPointRead])
_MONTHLY_LIST_ADAPTER = TypeAdapter(list[MonthlyTrendPointRead])
_CATEGORY_LIST_ADAPTER = TypeAdapter(list[CategoryCountRead])
_PRIORITY_LIST_ADAPTER = TypeAdapter(list[PriorityBandCountRead])
_RESPONSE_TIME_ADAPTER = TypeAdapter(ResponseTimeStatsRead)
_UNREAD_ADAPTER = TypeAdapter(UnreadSummaryRead)
_TASK_COMPLETION_ADAPTER = TypeAdapter(TaskCompletionStatsRead)
_REPORT_ADAPTER = TypeAdapter(AnalyticsReportRead)


def _validate_range(value: int, unit_days: int, settings: SettingsDep) -> None:
    """Raise if a caller-supplied window exceeds the configured cap.

    ``unit_days`` converts the caller's unit (1 for days, 7 for weeks, ~30
    for months) to days so every endpoint enforces the same underlying cap
    regardless of which unit it accepts.
    """
    max_range_days = settings.analytics.max_range_days
    if value * unit_days > max_range_days:
        raise ValidationError(
            f"Range too large: {value} exceeds the {max_range_days}-day cap."
        )


def _report_to_read(report: AnalyticsReport) -> AnalyticsReportRead:
    return AnalyticsReportRead(
        generated_at=report.generated_at,
        range_days=report.range_days,
        daily_email_volume=[
            TimeSeriesPointRead(period=p.period, count=p.count)
            for p in report.daily_email_volume
        ],
        weekly_email_volume=[
            TimeSeriesPointRead(period=p.period, count=p.count)
            for p in report.weekly_email_volume
        ],
        monthly_trends=[
            MonthlyTrendPointRead(
                month=p.month,
                email_count=p.email_count,
                task_count=p.task_count,
                avg_priority_score=p.avg_priority_score,
            )
            for p in report.monthly_trends
        ],
        category_distribution=[
            CategoryCountRead(category=r.category, count=r.count)
            for r in report.category_distribution
        ],
        priority_distribution=[
            PriorityBandCountRead(band=r.band, count=r.count)
            for r in report.priority_distribution
        ],
        response_time=ResponseTimeStatsRead(
            average_hours=report.response_time.average_hours,
            median_hours=report.response_time.median_hours,
            sample_size=report.response_time.sample_size,
        ),
        unread_summary=UnreadSummaryRead(
            total_unread=report.unread_summary.total_unread,
            by_category=[
                CategoryCountRead(category=r.category, count=r.count)
                for r in report.unread_summary.by_category
            ],
            by_age=[
                UnreadAgeBandCountRead(band=r.band, count=r.count)
                for r in report.unread_summary.by_age
            ],
        ),
        task_completion=TaskCompletionStatsRead(
            total_tasks=report.task_completion.total_tasks,
            completed_tasks=report.task_completion.completed_tasks,
            completion_rate=report.task_completion.completion_rate,
            daily_completions=[
                TimeSeriesPointRead(period=p.period, count=p.count)
                for p in report.task_completion.daily_completions
            ],
            by_priority=[
                TaskPriorityBreakdownRead(
                    priority=r.priority, total=r.total, completed=r.completed
                )
                for r in report.task_completion.by_priority
            ],
        ),
    )


@router.get(
    "/daily-emails",
    response_model=list[TimeSeriesPointRead],
    summary="Daily email volume",
)
async def daily_emails(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=30, ge=1, le=400),
) -> list[TimeSeriesPointRead]:
    """Emails received per day, zero-filled, for the last ``days`` days."""
    _validate_range(days, 1, settings)

    async def _compute() -> list[TimeSeriesPointRead]:
        points = await service.daily_email_volume(user.id, days=days)
        return [TimeSeriesPointRead(period=p.period, count=p.count) for p in points]

    return await cached(
        cache,
        cache_key("analytics", "daily-emails", user.id, days),
        adapter=_POINT_LIST_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/weekly-emails",
    response_model=list[TimeSeriesPointRead],
    summary="Weekly email volume",
)
async def weekly_emails(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    weeks: int = Query(default=12, ge=1, le=57),
) -> list[TimeSeriesPointRead]:
    """Emails received per week (Monday-aligned), zero-filled.

    Covers the last ``weeks`` weeks.
    """
    _validate_range(weeks, 7, settings)

    async def _compute() -> list[TimeSeriesPointRead]:
        points = await service.weekly_email_volume(user.id, weeks=weeks)
        return [TimeSeriesPointRead(period=p.period, count=p.count) for p in points]

    return await cached(
        cache,
        cache_key("analytics", "weekly-emails", user.id, weeks),
        adapter=_POINT_LIST_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/monthly-trends",
    response_model=list[MonthlyTrendPointRead],
    summary="Monthly email/task volume and priority trends",
)
async def monthly_trends(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    months: int = Query(default=12, ge=1, le=13),
) -> list[MonthlyTrendPointRead]:
    """Email volume, task volume, and avg priority per month, zero-filled."""
    _validate_range(months, 30, settings)

    async def _compute() -> list[MonthlyTrendPointRead]:
        points = await service.monthly_trends(user.id, months=months)
        return [
            MonthlyTrendPointRead(
                month=p.month,
                email_count=p.email_count,
                task_count=p.task_count,
                avg_priority_score=p.avg_priority_score,
            )
            for p in points
        ]

    return await cached(
        cache,
        cache_key("analytics", "monthly-trends", user.id, months),
        adapter=_MONTHLY_LIST_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/category-distribution",
    response_model=list[CategoryCountRead],
    summary="Email count by category",
)
async def category_distribution(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=90, ge=1, le=400),
) -> list[CategoryCountRead]:
    """Email count by category over the last ``days`` days."""
    _validate_range(days, 1, settings)

    async def _compute() -> list[CategoryCountRead]:
        rows = await service.category_distribution(user.id, days=days)
        return [CategoryCountRead(category=r.category, count=r.count) for r in rows]

    return await cached(
        cache,
        cache_key("analytics", "category-distribution", user.id, days),
        adapter=_CATEGORY_LIST_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/priority-distribution",
    response_model=list[PriorityBandCountRead],
    summary="Email count by priority band",
)
async def priority_distribution(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=90, ge=1, le=400),
) -> list[PriorityBandCountRead]:
    """Email count by priority band over the last ``days`` days."""
    _validate_range(days, 1, settings)

    async def _compute() -> list[PriorityBandCountRead]:
        rows = await service.priority_distribution(user.id, days=days)
        return [PriorityBandCountRead(band=r.band, count=r.count) for r in rows]

    return await cached(
        cache,
        cache_key("analytics", "priority-distribution", user.id, days),
        adapter=_PRIORITY_LIST_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/response-time",
    response_model=ResponseTimeStatsRead,
    summary="Average/median reply time",
)
async def response_time(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=30, ge=1, le=400),
) -> ResponseTimeStatsRead:
    """Average/median hours from an email's receipt to its sent reply."""
    _validate_range(days, 1, settings)

    async def _compute() -> ResponseTimeStatsRead:
        stats = await service.response_time_stats(user.id, days=days)
        return ResponseTimeStatsRead(
            average_hours=stats.average_hours,
            median_hours=stats.median_hours,
            sample_size=stats.sample_size,
        )

    return await cached(
        cache,
        cache_key("analytics", "response-time", user.id, days),
        adapter=_RESPONSE_TIME_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/unread-summary", response_model=UnreadSummaryRead, summary="Unread mail snapshot"
)
async def unread_summary(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
) -> UnreadSummaryRead:
    """Current unread-mail snapshot: total, by category, by how stale it is."""

    async def _compute() -> UnreadSummaryRead:
        summary = await service.unread_summary(user.id)
        return UnreadSummaryRead(
            total_unread=summary.total_unread,
            by_category=[
                CategoryCountRead(category=r.category, count=r.count)
                for r in summary.by_category
            ],
            by_age=[
                UnreadAgeBandCountRead(band=r.band, count=r.count)
                for r in summary.by_age
            ],
        )

    return await cached(
        cache,
        cache_key("analytics", "unread-summary", user.id),
        adapter=_UNREAD_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/task-completion",
    response_model=TaskCompletionStatsRead,
    summary="Task completion rate and trend",
)
async def task_completion(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=30, ge=1, le=400),
) -> TaskCompletionStatsRead:
    """Completion rate, a daily-completions trend, and a per-priority breakdown."""
    _validate_range(days, 1, settings)

    async def _compute() -> TaskCompletionStatsRead:
        stats = await service.task_completion_stats(user.id, days=days)
        return TaskCompletionStatsRead(
            total_tasks=stats.total_tasks,
            completed_tasks=stats.completed_tasks,
            completion_rate=stats.completion_rate,
            daily_completions=[
                TimeSeriesPointRead(period=p.period, count=p.count)
                for p in stats.daily_completions
            ],
            by_priority=[
                TaskPriorityBreakdownRead(
                    priority=r.priority, total=r.total, completed=r.completed
                )
                for r in stats.by_priority
            ],
        )

    return await cached(
        cache,
        cache_key("analytics", "task-completion", user.id, days),
        adapter=_TASK_COMPLETION_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get(
    "/report",
    response_model=AnalyticsReportRead,
    summary="Full combined analytics report",
)
async def full_report(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    cache: CacheServiceDep,
    days: int = Query(default=30, ge=1, le=400),
) -> AnalyticsReportRead:
    """Every chart in one payload -- what CSV/PDF export renders."""
    _validate_range(days, 1, settings)

    async def _compute() -> AnalyticsReportRead:
        report = await service.full_report(user.id, days=days)
        return _report_to_read(report)

    return await cached(
        cache,
        cache_key("analytics", "report", user.id, days),
        adapter=_REPORT_ADAPTER,
        ttl_seconds=settings.redis.default_ttl_seconds,
        compute=_compute,
    )


@router.get("/export.csv", summary="Export the analytics report as CSV")
async def export_csv(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    days: int = Query(default=30, ge=1, le=400),
) -> Response:
    """Download the full analytics report as a multi-section CSV file."""
    _validate_range(days, 1, settings)
    report = await service.full_report(user.id, days=days)
    csv_text = render_csv(report)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="analytics-report-{days}d.csv"'
            )
        },
    )


@router.get("/export.pdf", summary="Export the analytics report as PDF")
async def export_pdf(
    user: CurrentUserDep,
    service: AnalyticsServiceDep,
    settings: SettingsDep,
    days: int = Query(default=30, ge=1, le=400),
) -> Response:
    """Download the full analytics report as a formatted PDF file."""
    _validate_range(days, 1, settings)
    report = await service.full_report(user.id, days=days)
    pdf_bytes = render_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="analytics-report-{days}d.pdf"'
            )
        },
    )
