"""Scheduled cleanup: purges operational data past its retention window.

Deliberately scoped to data that is safe to lose without a user-facing
consequence -- expired/revoked sessions, old LLM prompt/response logs,
already-read notifications, and resolved retry-queue rows. Never touches
core business data (emails, tasks, memories, drafts), even when
soft-deleted; a real account-deletion flow (which this codebase does not
implement yet) would need to make that call explicitly and separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.core.time import utcnow
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.session import SessionRepository
from app.services.retry_queue import RetryQueueService


@dataclass
class CleanupResult:
    """How many rows the sweep purged, by category."""

    expired_sessions_purged: int
    prompt_logs_purged: int
    notifications_purged: int
    resolved_retry_jobs_purged: int
    notification_deliveries_purged: int

    @property
    def total(self) -> int:
        """Return the total number of rows purged across every category."""
        return (
            self.expired_sessions_purged
            + self.prompt_logs_purged
            + self.notifications_purged
            + self.resolved_retry_jobs_purged
            + self.notification_deliveries_purged
        )


class CleanupService:
    """Runs the scheduled data-retention sweep."""

    def __init__(
        self,
        session_repo: SessionRepository,
        prompt_log_repo: PromptLogRepository,
        notification_repo: NotificationRepository,
        retry_queue: RetryQueueService,
        notification_delivery_repo: NotificationDeliveryRepository,
    ) -> None:
        self._sessions = session_repo
        self._prompt_logs = prompt_log_repo
        self._notifications = notification_repo
        self._retry_queue = retry_queue
        self._notification_deliveries = notification_delivery_repo

    async def run(
        self,
        *,
        session_retention_days: int,
        prompt_log_retention_days: int,
        notification_retention_days: int,
        retry_job_retention_days: int,
        notification_delivery_retention_days: int,
    ) -> CleanupResult:
        """Purge every category past its own configured retention window."""
        now = utcnow()
        sessions_purged = await self._sessions.delete_expired_before(
            now - timedelta(days=session_retention_days)
        )
        prompt_logs_purged = await self._prompt_logs.delete_older_than(
            now - timedelta(days=prompt_log_retention_days)
        )
        notifications_purged = await self._notifications.delete_read_older_than(
            now - timedelta(days=notification_retention_days)
        )
        retry_jobs_purged = await self._retry_queue.purge_resolved_older_than(
            retention_days=retry_job_retention_days
        )
        notification_deliveries_purged = (
            await self._notification_deliveries.delete_older_than(
                now - timedelta(days=notification_delivery_retention_days)
            )
        )
        return CleanupResult(
            expired_sessions_purged=sessions_purged,
            prompt_logs_purged=prompt_logs_purged,
            notifications_purged=notifications_purged,
            resolved_retry_jobs_purged=retry_jobs_purged,
            notification_deliveries_purged=notification_deliveries_purged,
        )
