"""APScheduler wiring for periodic background jobs.

Three jobs run on independent intervals (see ``SchedulerSettings``):

* ``dispatch_due_reminders`` -- polls for pending :class:`~app.infra.models.
  reminder.Reminder` rows whose ``remind_at`` has passed and converts each
  into a :class:`~app.infra.models.notification.Notification`. Poll-based
  rather than one dynamically-scheduled APScheduler job per reminder: it
  needs no persistent job store and a reminder that was due while the
  process was down simply fires on the next poll after restart.
* ``sync_google_calendars`` -- pushes every configured user's pending
  calendar events to Google Calendar (see
  ``app/services/calendar_sync_service.py``).
* ``run_memory_decay_sweep`` -- recomputes every memory's importance score
  (see ``app/agents/memory_scoring.py``), closing the loop Phase 6 left
  unwired ("not wired to a scheduler -- this codebase has none yet").

Each job owns its own database session (jobs are not request-scoped) and
catches its own exceptions -- one job's failure must not stop the scheduler
or the other jobs from continuing to fire.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config.logging import get_logger
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.notification import Notification
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.reminder import ReminderRepository
from app.services.calendar_sync_service import sync_all_users
from app.services.memory import MemoryService
from app.services.reminder import ReminderService

logger = get_logger(__name__)


async def dispatch_due_reminders(database: Database) -> int:
    """Turn every due, pending reminder into a notification.

    Returns:
        The number of reminders dispatched.
    """
    async with database.session() as session:
        reminder_service = ReminderService(ReminderRepository(session))
        notification_repo = NotificationRepository(session)
        due = await reminder_service.list_due(now=datetime.now(UTC))
        for reminder in due:
            related_entity_type = "task" if reminder.task_id else "calendar_event"
            related_entity_id = reminder.task_id or reminder.calendar_event_id
            await notification_repo.add(
                Notification(
                    tenant_id=reminder.tenant_id,
                    user_id=reminder.user_id,
                    type="reminder",
                    title="Reminder",
                    body=reminder.message,
                    related_entity_type=related_entity_type,
                    related_entity_id=related_entity_id,
                )
            )
            await reminder_service.mark_sent(reminder.id)
        return len(due)


async def run_memory_decay_sweep(database: Database) -> int:
    """Recompute ``importance_score`` for every active memory, all users."""
    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        return await service.run_decay_sweep()


def build_scheduler(
    *,
    database: Database,
    settings: Settings,
    google_http_client: httpx.AsyncClient,
) -> AsyncIOScheduler:
    """Build (but do not start) the process-wide APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    calendar_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=settings.calendar.requests_per_second,
        burst_capacity=settings.calendar.burst_capacity,
    )

    async def _dispatch_reminders_job() -> None:
        try:
            count = await dispatch_due_reminders(database)
            if count:
                logger.info("reminders_dispatched", count=count)
        except Exception as exc:
            logger.warning("reminder_dispatch_job_failed", error=str(exc))

    async def _sync_calendars_job() -> None:
        try:
            count = await sync_all_users(
                database,
                settings,
                http_client=google_http_client,
                rate_limiter=calendar_rate_limiter,
            )
            if count:
                logger.info("calendar_events_synced", count=count)
        except Exception as exc:
            logger.warning("calendar_sync_job_failed", error=str(exc))

    async def _memory_decay_job() -> None:
        try:
            count = await run_memory_decay_sweep(database)
            logger.info("memory_decay_sweep_completed", rescored=count)
        except Exception as exc:
            logger.warning("memory_decay_job_failed", error=str(exc))

    scheduler.add_job(
        _dispatch_reminders_job,
        "interval",
        seconds=settings.scheduler.reminder_poll_interval_seconds,
        id="dispatch_due_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _sync_calendars_job,
        "interval",
        seconds=settings.scheduler.calendar_sync_interval_seconds,
        id="sync_google_calendars",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _memory_decay_job,
        "interval",
        hours=settings.scheduler.memory_decay_interval_hours,
        id="run_memory_decay_sweep",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
