"""Analytics response schemas -- chart-ready aggregates."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class TimeSeriesPointRead(BaseModel):
    """One point of a count-per-bucket chart."""

    period: date
    count: int


class MonthlyTrendPointRead(BaseModel):
    """One month of the monthly-trends chart."""

    month: date
    email_count: int
    task_count: int
    avg_priority_score: float | None


class CategoryCountRead(BaseModel):
    """One slice of the category-distribution chart."""

    category: str
    count: int


class PriorityBandCountRead(BaseModel):
    """One bar of the priority-distribution chart."""

    band: str
    count: int


class ResponseTimeStatsRead(BaseModel):
    """Average/median reply time, in hours."""

    average_hours: float | None
    median_hours: float | None
    sample_size: int


class UnreadAgeBandCountRead(BaseModel):
    """One bar of the unread-by-age chart."""

    band: str
    count: int


class UnreadSummaryRead(BaseModel):
    """Current-state snapshot of unread mail."""

    total_unread: int
    by_category: list[CategoryCountRead]
    by_age: list[UnreadAgeBandCountRead]


class TaskPriorityBreakdownRead(BaseModel):
    """One row of the task-completion-by-priority table."""

    priority: str
    total: int
    completed: int


class TaskCompletionStatsRead(BaseModel):
    """Task-completion metrics over a date range."""

    total_tasks: int
    completed_tasks: int
    completion_rate: float
    daily_completions: list[TimeSeriesPointRead]
    by_priority: list[TaskPriorityBreakdownRead]


class AnalyticsReportRead(BaseModel):
    """The full analytics payload -- one request for an interactive dashboard."""

    generated_at: datetime
    range_days: int
    daily_email_volume: list[TimeSeriesPointRead]
    weekly_email_volume: list[TimeSeriesPointRead]
    monthly_trends: list[MonthlyTrendPointRead]
    category_distribution: list[CategoryCountRead]
    priority_distribution: list[PriorityBandCountRead]
    response_time: ResponseTimeStatsRead
    unread_summary: UnreadSummaryRead
    task_completion: TaskCompletionStatsRead
