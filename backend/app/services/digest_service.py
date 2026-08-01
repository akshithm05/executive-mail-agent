"""Morning and weekly digest generation.

Deterministic, template-based content -- no LLM call, so digests generate
correctly even when the AI agent isn't configured (see
``AISettings.is_configured``). Reuses :class:`~app.services.dashboard.
DashboardService`'s aggregation so the numbers a digest reports always match
what the dashboard itself shows.

Each digest is stored as a :class:`~app.infra.models.summary.Summary` row
(``summary_type="daily_digest"``/``"weekly_digest"``) and surfaced as a
:class:`~app.infra.models.notification.Notification` so it shows up in the
same place every other AI-generated alert does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.infra.models.notification import Notification
from app.infra.models.summary import Summary
from app.infra.models.user import User
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.summary import SummaryRepository
from app.infra.repositories.task import TaskRepository
from app.services.dashboard import DashboardService, DashboardSummary
from app.services.notification_dispatch import NotificationDispatchService

_MODEL_NAME = "deterministic-digest-v1"


def _first_name(user: User) -> str:
    return user.display_name.split(" ")[0] if user.display_name else "there"


def _render_morning_digest(
    user: User, summary: DashboardSummary, deadline_titles: list[str]
) -> str:
    lines = [
        f"Good morning, {_first_name(user)}.",
        f"{summary.unread_emails} unread email(s), {summary.urgent_emails} urgent.",
        f"{summary.pending_tasks} open task(s), {summary.pending_drafts} draft "
        "reply(ies) waiting for review.",
    ]
    if deadline_titles:
        lines.append("Upcoming deadlines: " + "; ".join(deadline_titles))
    else:
        lines.append("No upcoming deadlines detected.")
    return "\n".join(lines)


def _render_weekly_digest(
    user: User,
    summary: DashboardSummary,
    *,
    emails_this_week: int,
    tasks_completed_this_week: int,
) -> str:
    lines = [
        f"Weekly recap for {_first_name(user)}.",
        f"{emails_this_week} email(s) received this week, "
        f"{tasks_completed_this_week} task(s) completed.",
        f"{summary.pending_tasks} task(s) still open, "
        f"{summary.urgent_emails} email(s) currently marked urgent.",
    ]
    if summary.category_counts:
        top = sorted(
            summary.category_counts.items(), key=lambda kv: kv[1], reverse=True
        )
        lines.append(
            "Top categories: " + ", ".join(f"{cat} ({count})" for cat, count in top[:3])
        )
    return "\n".join(lines)


class DigestService:
    """Builds and stores morning/weekly digests for one user at a time."""

    def __init__(
        self,
        dashboard_service: DashboardService,
        email_repo: EmailRepository,
        task_repo: TaskRepository,
        summary_repo: SummaryRepository,
        notification_repo: NotificationRepository,
        *,
        notification_dispatch: NotificationDispatchService | None = None,
    ) -> None:
        self._dashboard = dashboard_service
        self._emails = email_repo
        self._tasks = task_repo
        self._summaries = summary_repo
        self._notifications = notification_repo
        self._notification_dispatch = notification_dispatch

    async def build_morning_digest(self, user: User, tenant_id: uuid.UUID) -> Summary:
        """Build and store today's morning digest for one user."""
        summary = await self._dashboard.summarize(user.id)
        deadlines = await self._emails.list_upcoming_deadlines(
            user.id, now=datetime.now(UTC), limit=5
        )
        content = _render_morning_digest(
            user, summary, [e.subject or "(no subject)" for e in deadlines]
        )
        return await self._store(
            user, tenant_id, "daily_digest", content, "morning_digest"
        )

    async def build_weekly_digest(self, user: User, tenant_id: uuid.UUID) -> Summary:
        """Build and store this week's digest for one user."""
        since = datetime.now(UTC) - timedelta(days=7)
        summary = await self._dashboard.summarize(user.id)
        emails_this_week = await self._emails.count_received_since(user.id, since=since)
        tasks_completed = await self._tasks.count_completed_since(user.id, since=since)
        content = _render_weekly_digest(
            user,
            summary,
            emails_this_week=emails_this_week,
            tasks_completed_this_week=tasks_completed,
        )
        return await self._store(
            user, tenant_id, "weekly_digest", content, "weekly_digest"
        )

    async def _store(
        self,
        user: User,
        tenant_id: uuid.UUID,
        summary_type: str,
        content: str,
        notification_type: str,
    ) -> Summary:
        summary_row = await self._summaries.add(
            Summary(
                tenant_id=tenant_id,
                user_id=user.id,
                summary_type=summary_type,
                content=content,
                model_name=_MODEL_NAME,
            )
        )
        notification = await self._notifications.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user.id,
                type=notification_type,
                title="Your morning digest is ready"
                if notification_type == "morning_digest"
                else "Your weekly digest is ready",
                body=content.splitlines()[0] if content else "",
                related_entity_type="summary",
                related_entity_id=summary_row.id,
            )
        )
        if self._notification_dispatch is not None:
            await self._notification_dispatch.dispatch(notification)
        return summary_row
