"""Analytics: chart-ready aggregates over emails/tasks/draft replies.

Every method fetches one bounded pool of rows (see ``app/infra/repositories/
email.py``'s ``list_received_between`` and its siblings on ``TaskRepository``/
``DraftReplyRepository``) and aggregates it in Python, rather than pushing
date-bucketing into SQL. That's a deliberate choice, not an oversight: this
codebase's test suite runs against SQLite while production runs Postgres,
and the two have incompatible date-truncation functions (``strftime`` vs.
``date_trunc``) -- exactly the kind of dialect-specific SQL that bit this
project once already (see the naive/aware datetime lesson baked into
``app/core/time.py``). Aggregating a bounded row set in Python sidesteps
that whole class of bug at a mailbox's realistic scale.

Every time-series method zero-fills empty buckets (a day with no emails
still gets a ``count=0`` point) so a chart renders a continuous axis rather
than silently skipping gaps.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.core.time import utcnow
from app.infra.models.draft_reply import DraftReply
from app.infra.models.email import Email
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.task import TaskRepository

# Same fixed priority_score bands the dashboard's heatmap already uses (see
# app/services/dashboard.py) -- reused verbatim so "priority distribution"
# here and the dashboard's heatmap always agree on band boundaries.
_PRIORITY_BANDS = (
    (0.0, 0.2, "0-20"),
    (0.2, 0.4, "20-40"),
    (0.4, 0.6, "40-60"),
    (0.6, 0.8, "60-80"),
    (0.8, 1.01, "80-100"),
)

_UNREAD_AGE_BANDS = (
    (0.0, 1.0, "<1 day"),
    (1.0, 3.0, "1-3 days"),
    (3.0, 7.0, "3-7 days"),
    (7.0, float("inf"), "7+ days"),
)


def _priority_band(score: float) -> str:
    for low, high, label in _PRIORITY_BANDS:
        if low <= score < high:
            return label
    return "80-100"


def _unread_age_band(age_days: float) -> str:
    for low, high, label in _UNREAD_AGE_BANDS:
        if low <= age_days < high:
            return label
    return "7+ days"


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _add_months(day: date, months: int) -> date:
    total = (day.year * 12 + (day.month - 1)) + months
    return date(total // 12, total % 12 + 1, 1)


@dataclass
class TimeSeriesPoint:
    """One point of a count-per-bucket chart (daily/weekly volume, task completions)."""

    period: date
    count: int


@dataclass
class MonthlyTrendPoint:
    """One month of the monthly-trends chart -- volume plus quality signals."""

    month: date
    email_count: int
    task_count: int
    avg_priority_score: float | None


@dataclass
class CategoryCount:
    """One slice of the category-distribution chart."""

    category: str
    count: int


@dataclass
class PriorityBandCount:
    """One bar of the priority-distribution chart."""

    band: str
    count: int


@dataclass
class ResponseTimeStats:
    """Aggregate stats for how long it takes to send a reply, in hours."""

    average_hours: float | None
    median_hours: float | None
    sample_size: int


@dataclass
class UnreadAgeBandCount:
    """One bar of the unread-by-age chart."""

    band: str
    count: int


@dataclass
class UnreadSummary:
    """Current-state snapshot of unread mail.

    Not a time series -- see the module docstring.
    """

    total_unread: int
    by_category: list[CategoryCount] = field(default_factory=list)
    by_age: list[UnreadAgeBandCount] = field(default_factory=list)


@dataclass
class TaskPriorityBreakdown:
    """One row of the task-completion-by-priority table."""

    priority: str
    total: int
    completed: int


@dataclass
class TaskCompletionStats:
    """Aggregate task-completion metrics over a date range."""

    total_tasks: int
    completed_tasks: int
    completion_rate: float
    daily_completions: list[TimeSeriesPoint] = field(default_factory=list)
    by_priority: list[TaskPriorityBreakdown] = field(default_factory=list)


@dataclass
class AnalyticsReport:
    """The full analytics payload -- what CSV/PDF export renders."""

    generated_at: datetime
    range_days: int
    daily_email_volume: list[TimeSeriesPoint]
    weekly_email_volume: list[TimeSeriesPoint]
    monthly_trends: list[MonthlyTrendPoint]
    category_distribution: list[CategoryCount]
    priority_distribution: list[PriorityBandCount]
    response_time: ResponseTimeStats
    unread_summary: UnreadSummary
    task_completion: TaskCompletionStats


def _bucket_counts(
    items: Sequence[date], *, buckets: list[date], bucket_fn: Callable[[date], date]
) -> list[TimeSeriesPoint]:
    counts = Counter(bucket_fn(item) for item in items)
    return [TimeSeriesPoint(period=b, count=counts.get(b, 0)) for b in buckets]


def _daily_buckets(since: date, until: date) -> list[date]:
    days = (until - since).days
    return [since + timedelta(days=i) for i in range(days + 1)]


def _weekly_buckets(since: date, until: date) -> list[date]:
    start = _week_start(since)
    end = _week_start(until)
    buckets = []
    cursor = start
    while cursor <= end:
        buckets.append(cursor)
        cursor += timedelta(days=7)
    return buckets


def _monthly_buckets(since: date, until: date) -> list[date]:
    start = _month_start(since)
    end = _month_start(until)
    buckets = []
    cursor = start
    while cursor <= end:
        buckets.append(cursor)
        cursor = _add_months(cursor, 1)
    return buckets


class AnalyticsService:
    """Computes chart-ready analytics aggregates for one user at a time."""

    def __init__(
        self,
        email_repo: EmailRepository,
        task_repo: TaskRepository,
        draft_reply_repo: DraftReplyRepository,
        *,
        row_fetch_limit: int = 20_000,
    ) -> None:
        self._emails = email_repo
        self._tasks = task_repo
        self._drafts = draft_reply_repo
        self._row_fetch_limit = row_fetch_limit

    async def daily_email_volume(
        self, user_id: uuid.UUID, *, days: int
    ) -> list[TimeSeriesPoint]:
        """Emails received per day, zero-filled, for the last ``days`` days."""
        now = utcnow()
        since = now - timedelta(days=days)
        emails = await self._emails.list_received_between(
            user_id, since=since, limit=self._row_fetch_limit
        )
        received_dates = [e.received_at.date() for e in emails]
        buckets = _daily_buckets(since.date(), now.date())
        return _bucket_counts(received_dates, buckets=buckets, bucket_fn=lambda d: d)

    async def weekly_email_volume(
        self, user_id: uuid.UUID, *, weeks: int
    ) -> list[TimeSeriesPoint]:
        """Emails received per week (Monday-aligned), zero-filled.

        Covers the last ``weeks`` weeks.
        """
        now = utcnow()
        since = now - timedelta(weeks=weeks)
        emails = await self._emails.list_received_between(
            user_id, since=since, limit=self._row_fetch_limit
        )
        received_dates = [e.received_at.date() for e in emails]
        buckets = _weekly_buckets(since.date(), now.date())
        return _bucket_counts(received_dates, buckets=buckets, bucket_fn=_week_start)

    async def monthly_trends(
        self, user_id: uuid.UUID, *, months: int
    ) -> list[MonthlyTrendPoint]:
        """Email volume, task volume, and avg priority per month, zero-filled."""
        now = utcnow()
        since = _add_months(now.date(), -months)
        since_dt = datetime.combine(since, datetime.min.time())

        emails = await self._emails.list_received_between(
            user_id, since=since_dt, limit=self._row_fetch_limit
        )
        tasks = await self._tasks.list_for_analytics(
            user_id, since=since_dt, limit=self._row_fetch_limit
        )

        buckets = _monthly_buckets(since, now.date())
        emails_by_month: dict[date, list[Email]] = {b: [] for b in buckets}
        for email in emails:
            bucket = _month_start(email.received_at.date())
            if bucket in emails_by_month:
                emails_by_month[bucket].append(email)

        tasks_by_month: Counter[date] = Counter()
        for task in tasks:
            bucket = _month_start(task.created_at.date())
            if bucket in emails_by_month:
                tasks_by_month[bucket] += 1

        points: list[MonthlyTrendPoint] = []
        for bucket in buckets:
            month_emails = emails_by_month[bucket]
            scores = [
                e.priority_score for e in month_emails if e.priority_score is not None
            ]
            avg_score = sum(scores) / len(scores) if scores else None
            points.append(
                MonthlyTrendPoint(
                    month=bucket,
                    email_count=len(month_emails),
                    task_count=tasks_by_month.get(bucket, 0),
                    avg_priority_score=avg_score,
                )
            )
        return points

    async def category_distribution(
        self, user_id: uuid.UUID, *, days: int
    ) -> list[CategoryCount]:
        """Email count by category over the last ``days`` days."""
        emails = await self._emails.list_received_between(
            user_id, since=utcnow() - timedelta(days=days), limit=self._row_fetch_limit
        )
        counts = Counter(e.category for e in emails if e.category is not None)
        return [
            CategoryCount(category=category, count=count)
            for category, count in sorted(
                counts.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

    async def priority_distribution(
        self, user_id: uuid.UUID, *, days: int
    ) -> list[PriorityBandCount]:
        """Email count by priority band over the last ``days`` days."""
        emails = await self._emails.list_received_between(
            user_id, since=utcnow() - timedelta(days=days), limit=self._row_fetch_limit
        )
        counts = Counter(
            _priority_band(e.priority_score)
            for e in emails
            if e.priority_score is not None
        )
        return [
            PriorityBandCount(band=label, count=counts.get(label, 0))
            for _, _, label in _PRIORITY_BANDS
        ]

    async def response_time_stats(
        self, user_id: uuid.UUID, *, days: int
    ) -> ResponseTimeStats:
        """Average/median hours from an email's ``received_at`` to its sent reply."""
        drafts = await self._drafts.list_sent_between(
            user_id, since=utcnow() - timedelta(days=days), limit=self._row_fetch_limit
        )
        hours = [h for h in (_response_hours(d) for d in drafts) if h is not None]
        if not hours:
            return ResponseTimeStats(
                average_hours=None, median_hours=None, sample_size=0
            )
        return ResponseTimeStats(
            average_hours=statistics.mean(hours),
            median_hours=statistics.median(hours),
            sample_size=len(hours),
        )

    async def unread_summary(self, user_id: uuid.UUID) -> UnreadSummary:
        """Current unread-mail snapshot: total, by category, by how stale it is."""
        emails = await self._emails.list_unread(user_id, limit=self._row_fetch_limit)
        now = utcnow()

        category_counts = Counter(e.category for e in emails if e.category is not None)
        by_category = [
            CategoryCount(category=category, count=count)
            for category, count in sorted(
                category_counts.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

        age_counts = Counter(
            _unread_age_band((now - e.received_at).total_seconds() / 86400.0)
            for e in emails
        )
        by_age = [
            UnreadAgeBandCount(band=label, count=age_counts.get(label, 0))
            for _, _, label in _UNREAD_AGE_BANDS
        ]

        return UnreadSummary(
            total_unread=len(emails), by_category=by_category, by_age=by_age
        )

    async def task_completion_stats(
        self, user_id: uuid.UUID, *, days: int
    ) -> TaskCompletionStats:
        """Completion rate, a daily-completions trend, and a per-priority breakdown."""
        now = utcnow()
        since = now - timedelta(days=days)
        tasks = await self._tasks.list_for_analytics(
            user_id, since=since, limit=self._row_fetch_limit
        )

        completed = [
            t for t in tasks if t.status == "completed" and t.completed_at is not None
        ]
        completion_rate = len(completed) / len(tasks) if tasks else 0.0

        buckets = _daily_buckets(since.date(), now.date())
        completed_dates = [
            t.completed_at.date() for t in completed if t.completed_at is not None
        ]
        daily_completions = _bucket_counts(
            completed_dates, buckets=buckets, bucket_fn=lambda d: d
        )

        by_priority_counter: dict[str, list[int]] = {}
        for task in tasks:
            row = by_priority_counter.setdefault(task.priority, [0, 0])
            row[0] += 1
            if task.status == "completed" and task.completed_at is not None:
                row[1] += 1
        by_priority = [
            TaskPriorityBreakdown(priority=priority, total=row[0], completed=row[1])
            for priority, row in sorted(by_priority_counter.items())
        ]

        return TaskCompletionStats(
            total_tasks=len(tasks),
            completed_tasks=len(completed),
            completion_rate=completion_rate,
            daily_completions=daily_completions,
            by_priority=by_priority,
        )

    async def full_report(self, user_id: uuid.UUID, *, days: int) -> AnalyticsReport:
        """Compute every chart in one payload -- what CSV/PDF export renders.

        Calls the individual per-chart methods (each re-fetches its own
        bounded row set) rather than sharing one fetch across all of them --
        export is an infrequent operation, so the extra queries trade a
        little efficiency for keeping every method independently simple and
        correct. Time-series windows are derived from ``days`` in the units
        each chart naturally uses (weeks, months).
        """
        weeks = max(days // 7, 1)
        months = max(days // 30, 1)
        return AnalyticsReport(
            generated_at=utcnow(),
            range_days=days,
            daily_email_volume=await self.daily_email_volume(user_id, days=days),
            weekly_email_volume=await self.weekly_email_volume(user_id, weeks=weeks),
            monthly_trends=await self.monthly_trends(user_id, months=months),
            category_distribution=await self.category_distribution(user_id, days=days),
            priority_distribution=await self.priority_distribution(user_id, days=days),
            response_time=await self.response_time_stats(user_id, days=days),
            unread_summary=await self.unread_summary(user_id),
            task_completion=await self.task_completion_stats(user_id, days=days),
        )


def _response_hours(draft: DraftReply) -> float | None:
    if draft.sent_at is None or draft.email is None:
        return None
    delta = draft.sent_at - draft.email.received_at
    hours = delta.total_seconds() / 3600.0
    return max(hours, 0.0)
