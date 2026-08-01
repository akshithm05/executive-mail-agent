"""Dashboard summary aggregation.

Powers the frontend's overview page (stat tiles, category chart, priority
heatmap) with a single request instead of the client fanning out to five
separate list endpoints and computing counts itself. Reads only -- this
service never mutates anything.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.task import TaskRepository

# Fixed priority_score bands (0.0-1.0) the heatmap buckets into. Order
# matters: checked low-to-high, last band is inclusive of 1.0.
_PRIORITY_BANDS = (
    (0.0, 0.2, "0-20"),
    (0.2, 0.4, "20-40"),
    (0.4, 0.6, "40-60"),
    (0.6, 0.8, "60-80"),
    (0.8, 1.01, "80-100"),
)


def _priority_band(score: float) -> str:
    for low, high, label in _PRIORITY_BANDS:
        if low <= score < high:
            return label
    return "80-100"


@dataclass
class DashboardSummary:
    """Aggregate counts and chart-ready data for the overview dashboard."""

    total_emails: int
    unread_emails: int
    urgent_emails: int
    upcoming_deadlines: int
    pending_tasks: int
    pending_drafts: int
    unread_notifications: int
    category_counts: dict[str, int] = field(default_factory=dict)
    # (category, priority_band) -> count, flattened for the API response.
    priority_heatmap: list[dict[str, object]] = field(default_factory=list)


class DashboardService:
    """Aggregates counts and chart data across emails/tasks/drafts/notifications."""

    def __init__(
        self,
        email_repo: EmailRepository,
        task_repo: TaskRepository,
        notification_repo: NotificationRepository,
        draft_reply_repo: DraftReplyRepository,
    ) -> None:
        self._emails = email_repo
        self._tasks = task_repo
        self._notifications = notification_repo
        self._drafts = draft_reply_repo

    async def summarize(self, user_id: uuid.UUID) -> DashboardSummary:
        """Compute the full dashboard summary for one user."""
        now = datetime.now(UTC)

        total_emails = await self._emails.count_total(user_id)
        unread_emails = await self._emails.count_unread(user_id)
        urgent_emails = await self._emails.count_urgent(user_id)
        upcoming_deadlines = await self._emails.count_upcoming_deadlines(
            user_id, now=now
        )
        pending_tasks = await self._tasks.count_pending(user_id)
        unread_notifications = await self._notifications.count_unread(user_id)
        pending_drafts = len(await self._drafts.list_by_user(user_id, status="draft"))

        category_rows = await self._emails.category_counts(user_id)
        category_counts = dict(category_rows)

        heatmap_rows = await self._emails.heatmap_rows(user_id)
        heatmap_counter: Counter[tuple[str, str]] = Counter()
        for category, score in heatmap_rows:
            heatmap_counter[(category, _priority_band(score))] += 1
        priority_heatmap = [
            {"category": category, "priority_band": band, "count": count}
            for (category, band), count in sorted(heatmap_counter.items())
        ]

        return DashboardSummary(
            total_emails=total_emails,
            unread_emails=unread_emails,
            urgent_emails=urgent_emails,
            upcoming_deadlines=upcoming_deadlines,
            pending_tasks=pending_tasks,
            pending_drafts=pending_drafts,
            unread_notifications=unread_notifications,
            category_counts=category_counts,
            priority_heatmap=priority_heatmap,
        )
