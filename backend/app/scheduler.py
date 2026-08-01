"""APScheduler wiring for every periodic background job.

Each job is wrapped in :func:`~app.infra.metrics.track_job` (duration +
success/failure metrics) inside its own try/except -- a job's failure is
logged and never stops the scheduler or any other job from continuing to
fire. This is the fault-tolerance contract every job in this module follows:

* ``dispatch_due_reminders`` -- the **Reminder Engine**: polls for pending
  reminders whose ``remind_at`` has passed and converts each into a
  notification. Per-reminder try/except so one bad reminder can't block the
  rest of the same batch.
* ``poll_gmail`` -- **Email polling**: the entry point that keeps the local
  mailbox mirror current without a Gmail push-notification webhook (see
  ``app/services/email_polling_service.py``).
* ``sync_google_calendars`` -- pushes pending calendar events to Google
  Calendar.
* ``send_morning_digests`` / ``send_weekly_digests`` -- **Morning/Weekly
  Digest**: deterministic per-user recap, stored as a ``Summary`` and
  surfaced as a ``Notification`` (see ``app/services/digest_service.py``).
* ``run_memory_consolidation`` -- **Memory Consolidation**: proactively
  collapses each user's accumulated low-signal memories per type (see
  ``MemoryService.maybe_summarize``), beyond the reactive
  per-email-triage-run calls Phase 6 already makes.
* ``run_memory_decay_sweep`` -- recomputes every memory's importance score.
* ``run_cleanup_sweep`` -- **Cleanup Jobs**: purges operational data past
  its retention window (see ``app/services/cleanup_service.py``).
* ``process_retry_queue`` -- **Retry Queue** / **Dead Letter Queue**: drains
  due entries from the generic failed-job table (see
  ``app/services/retry_queue.py``), dispatching by ``job_type`` back to the
  operation that failed; a job that exhausts its attempts here flips to
  ``dead_letter`` and stops being retried automatically.
* ``run_health_check_sweep`` -- **Health Checks**: a periodic self-check
  (DB connectivity, queue depths) distinct from the on-demand
  ``/health/*`` HTTP probes -- this one runs continuously and feeds the
  ``aeea_health_check_status`` **metric**.
* ``backfill_email_embeddings`` -- computes embeddings (see
  ``app/agents/embeddings.py``) for any email that doesn't have one yet,
  one bounded batch per run, powering AI-powered search's semantic ranking
  (see ``app/services/email_search.py``).

Every job owns its own database session (jobs are not request-scoped).
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.claude_client import StructuredLLMClient
from app.agents.email_agent import run_email_triage
from app.agents.embeddings import HashingEmbeddingProvider
from app.config.logging import get_logger
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.gmail_client import GmailClient
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.metrics import (
    AI_PROCESSING_QUEUE_DEPTH,
    DEAD_LETTER_QUEUE_DEPTH,
    HEALTH_CHECK_STATUS,
    RETRY_ATTEMPTS_TOTAL,
    RETRY_QUEUE_DEPTH,
    track_job,
)
from app.infra.models.memory import MEMORY_TYPES
from app.infra.models.notification import Notification
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.infra.repositories.attachment import AttachmentRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.reminder import ReminderRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.summary import SummaryRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.calendar_sync_service import sync_all_users
from app.services.cleanup_service import CleanupResult, CleanupService
from app.services.dashboard import DashboardService
from app.services.digest_service import DigestService
from app.services.email_ingestion_service import EmailIngestionService
from app.services.email_polling_service import poll_all_users
from app.services.google_auth_service import GoogleAuthService
from app.services.memory import MemoryService
from app.services.notification_dispatch import build_notification_dispatch_service
from app.services.reminder import ReminderService
from app.services.retry_queue import RetryQueueService

logger = get_logger(__name__)


async def dispatch_due_reminders(
    database: Database, settings: Settings, *, http_client: httpx.AsyncClient
) -> int:
    """Turn every due, pending reminder into a notification (the Reminder Engine).

    Every dispatched notification is also fanned out to the user's
    configured external channels (Slack/Discord/Telegram/WhatsApp/push/
    email/webhook) -- see ``app/services/notification_dispatch.py``. That
    fan-out is itself entirely best-effort (each channel isolates its own
    failures internally), so it never affects whether this reminder is
    marked sent.

    Returns:
        The number of reminders dispatched.
    """
    async with database.session() as session:
        reminder_service = ReminderService(ReminderRepository(session))
        notification_repo = NotificationRepository(session)
        notification_dispatch = build_notification_dispatch_service(
            session, settings, http_client
        )
        due = await reminder_service.list_due(now=utcnow())
        dispatched = 0
        for reminder in due:
            try:
                related_entity_type = "task" if reminder.task_id else "calendar_event"
                related_entity_id = reminder.task_id or reminder.calendar_event_id
                notification = await notification_repo.add(
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
                await notification_dispatch.dispatch(notification)
                await reminder_service.mark_sent(reminder.id)
                dispatched += 1
            except Exception:
                # One bad reminder must not block the rest of this batch --
                # it stays "pending" and is retried on the next sweep.
                logger.exception(
                    "reminder_dispatch_failed", reminder_id=str(reminder.id)
                )
        return dispatched


async def backfill_email_embeddings(database: Database, settings: Settings) -> int:
    """Compute embeddings for emails that don't have one yet (AI-powered search).

    Deliberately dependency-free -- ``HashingEmbeddingProvider`` is a local,
    deterministic embedding (see ``app/agents/embeddings.py``), not an
    Anthropic API call, so this runs regardless of ``settings.ai.is_configured``
    and costs nothing. Bounded to one batch per run (see
    ``SchedulerSettings.email_embedding_backfill_batch_size``) so a large
    backlog fills in gradually across repeated runs instead of blocking the
    scheduler with one enormous sweep.

    Returns:
        The number of emails embedded in this run.
    """
    embedding_provider = HashingEmbeddingProvider(
        dimensions=settings.memory.embedding_dimensions
    )
    async with database.session() as session:
        email_repo = EmailRepository(session)
        candidates = await email_repo.list_missing_embeddings(
            limit=settings.scheduler.email_embedding_backfill_batch_size
        )
        embedded = 0
        for email in candidates:
            try:
                text = f"{email.subject}\n{email.snippet or email.body_text or ''}"
                embedding = embedding_provider.embed(text)
                await email_repo.update_fields(
                    email.id,
                    embedding=embedding,
                    embedding_model=embedding_provider.model_name,
                )
                embedded += 1
            except Exception:
                # One bad email must not block the rest of this batch -- it
                # stays embedding-less and is retried on the next sweep.
                logger.exception("email_embedding_failed", email_id=str(email.id))
        return embedded


async def run_memory_decay_sweep(database: Database) -> int:
    """Recompute ``importance_score`` for every active memory, all users."""
    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        return await service.run_decay_sweep()


async def run_memory_consolidation(
    database: Database,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> int:
    """Proactively consolidate every user's low-signal memories, per type.

    A no-op when the AI agent isn't configured -- consolidation calls Claude
    (see ``MemoryService.maybe_summarize``), so it degrades the same way the
    rest of the AI pipeline does rather than failing every user's attempt
    individually. ``http_client`` is a test-only injection point for a
    custom Anthropic transport (mirrors ``app/agents/email_agent.py``'s
    ``run_email_triage``); production always leaves it ``None``.

    Returns:
        The number of (user, memory_type) pairs actually consolidated.
    """
    if not settings.ai.is_configured:
        logger.warning("memory_consolidation_skipped_not_configured")
        return 0

    async with database.session() as session:
        users = await UserRepository(session).list(limit=10_000)
        memory_service = MemoryService(
            MemoryRepository(session),
            half_life_days=settings.memory.decay_half_life_days,
            summarization_threshold=settings.memory.summarization_threshold,
        )
        embedding_provider = HashingEmbeddingProvider(
            dimensions=settings.memory.embedding_dimensions
        )
        raw_client = AsyncAnthropic(
            api_key=settings.ai.anthropic_api_key,
            timeout=settings.ai.request_timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )
        consolidated = 0
        try:
            claude_client = StructuredLLMClient(
                raw_client, settings.ai, PromptLogRepository(session)
            )
            for user in users:
                for memory_type in MEMORY_TYPES:
                    try:
                        result = await memory_service.maybe_summarize(
                            tenant_id=user.tenant_id,
                            user_id=user.id,
                            memory_type=memory_type,
                            claude_client=claude_client,
                            embedding_provider=embedding_provider,
                        )
                        if result is not None:
                            consolidated += 1
                    except Exception:
                        logger.exception(
                            "memory_consolidation_failed",
                            user_id=str(user.id),
                            memory_type=memory_type,
                        )
        finally:
            if http_client is None:
                await raw_client.close()
        return consolidated


def _build_dashboard_service(session: AsyncSession) -> DashboardService:
    return DashboardService(
        EmailRepository(session),
        TaskRepository(session),
        NotificationRepository(session),
        DraftReplyRepository(session),
    )


async def send_morning_digests(
    database: Database, settings: Settings, *, http_client: httpx.AsyncClient
) -> int:
    """Build and store today's morning digest for every user."""
    return await _send_digests(
        database, settings, http_client=http_client, kind="morning"
    )


async def send_weekly_digests(
    database: Database, settings: Settings, *, http_client: httpx.AsyncClient
) -> int:
    """Build and store this week's digest for every user."""
    return await _send_digests(
        database, settings, http_client=http_client, kind="weekly"
    )


async def _send_digests(
    database: Database, settings: Settings, *, http_client: httpx.AsyncClient, kind: str
) -> int:
    async with database.session() as session:
        users = await UserRepository(session).list(limit=10_000)
        digest_service = DigestService(
            _build_dashboard_service(session),
            EmailRepository(session),
            TaskRepository(session),
            SummaryRepository(session),
            NotificationRepository(session),
            notification_dispatch=build_notification_dispatch_service(
                session, settings, http_client
            ),
        )
        sent = 0
        for user in users:
            try:
                if kind == "morning":
                    await digest_service.build_morning_digest(user, user.tenant_id)
                else:
                    await digest_service.build_weekly_digest(user, user.tenant_id)
                sent += 1
            except Exception:
                logger.exception("digest_build_failed", kind=kind, user_id=str(user.id))
        return sent


async def run_cleanup_sweep(database: Database, settings: Settings) -> CleanupResult:
    """Purge operational data past its retention window (Cleanup Jobs)."""
    async with database.session() as session:
        cleanup_service = CleanupService(
            SessionRepository(session),
            PromptLogRepository(session),
            NotificationRepository(session),
            RetryQueueService(FailedJobRepository(session)),
            NotificationDeliveryRepository(session),
        )
        return await cleanup_service.run(
            session_retention_days=settings.scheduler.session_retention_days,
            prompt_log_retention_days=settings.scheduler.prompt_log_retention_days,
            notification_retention_days=settings.scheduler.notification_retention_days,
            retry_job_retention_days=settings.scheduler.retry_job_retention_days,
            notification_delivery_retention_days=settings.notification.delivery_retention_days,
        )


async def process_retry_queue(
    database: Database,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    rate_limiter: TokenBucketRateLimiter,
    event_bus: EventBus,
    ai_queue: AIProcessingQueue,
) -> int:
    """Drain due entries from the retry queue, dispatching by ``job_type``.

    A job that exhausts its attempts flips to ``dead_letter`` (see
    ``RetryQueueService.record_failure``) and is no longer retried
    automatically -- it stays queryable via
    ``GET /api/v1/system/failed-jobs`` for manual inspection/replay.

    Returns:
        The number of retry attempts processed (success or failure).
    """
    async with database.session() as session:
        retry_queue = RetryQueueService(FailedJobRepository(session))
        due_jobs = await retry_queue.list_due(limit=50)
        for job in due_jobs:
            try:
                if job.job_type == "ai_triage":
                    await _retry_ai_triage(database, settings, job.payload)
                elif job.job_type == "email_ingestion":
                    await _retry_email_ingestion(
                        session,
                        settings,
                        http_client=http_client,
                        rate_limiter=rate_limiter,
                        event_bus=event_bus,
                        ai_queue=ai_queue,
                        payload=job.payload,
                    )
                elif job.job_type == "notification_delivery":
                    await _retry_notification_delivery(
                        session, settings, http_client=http_client, payload=job.payload
                    )
                else:
                    raise ValueError(f"unknown job_type: {job.job_type!r}")
            except Exception as exc:
                await retry_queue.record_failure(job, exc)
                RETRY_ATTEMPTS_TOTAL.labels(
                    job_type=job.job_type, outcome="failure"
                ).inc()
            else:
                await retry_queue.record_success(job)
                RETRY_ATTEMPTS_TOTAL.labels(
                    job_type=job.job_type, outcome="success"
                ).inc()

        RETRY_QUEUE_DEPTH.set(await retry_queue.count_pending())
        DEAD_LETTER_QUEUE_DEPTH.set(await retry_queue.count_dead_letter())
        return len(due_jobs)


async def _retry_ai_triage(
    database: Database, settings: Settings, payload: dict[str, Any]
) -> None:
    job = AIProcessingJob(
        tenant_id=uuid.UUID(str(payload["tenant_id"])),
        user_id=uuid.UUID(str(payload["user_id"])),
        email_id=uuid.UUID(str(payload["email_id"])),
        gmail_message_id=str(payload["gmail_message_id"]),
    )
    await run_email_triage(job, database, settings)


async def _retry_email_ingestion(
    session: AsyncSession,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    rate_limiter: TokenBucketRateLimiter,
    event_bus: EventBus,
    ai_queue: AIProcessingQueue,
    payload: dict[str, Any],
) -> None:
    user_id = uuid.UUID(str(payload["user_id"]))
    message_id = str(payload["message_id"])

    user_repo = UserRepository(session)
    user = await user_repo.get(user_id)
    if user is None:
        return  # the user no longer exists; nothing left to retry

    auth_service = GoogleAuthService(
        settings=settings,
        oauth_client=GoogleOAuthClient(http_client, settings.oauth),
        cipher=TokenCipher(settings.security.token_encryption_key),
        user_repo=user_repo,
        tenant_repo=TenantRepository(session),
        credential_repo=GoogleCredentialRepository(session),
        session_repo=SessionRepository(session),
        db_session=session,
    )
    access_token = await auth_service.get_valid_access_token(user)
    gmail_client = GmailClient(http_client, settings.gmail, access_token, rate_limiter)
    ingestion_service = EmailIngestionService(
        gmail_client=gmail_client,
        email_repo=EmailRepository(session),
        attachment_repo=AttachmentRepository(session),
        event_bus=event_bus,
        ai_queue=ai_queue,
        db_session=session,
    )
    await ingestion_service.ingest_message(user, message_id)


async def _retry_notification_delivery(
    session: AsyncSession,
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> None:
    notification_dispatch = build_notification_dispatch_service(
        session, settings, http_client
    )
    device_id = payload.get("device_id")
    await notification_dispatch.retry_one(
        notification_id=uuid.UUID(str(payload["notification_id"])),
        channel_type=str(payload["channel_type"]),
        target=str(payload["target"]),
        device_id=uuid.UUID(str(device_id)) if device_id else None,
    )


async def run_health_check_sweep(
    database: Database,
    settings: Settings,
    *,
    ai_processing_queue: AIProcessingQueue,
) -> bool:
    """Self-check DB connectivity and queue depths; record to metrics.

    Distinct from the on-demand ``/health/ready`` HTTP probe -- this one
    runs continuously in the background and is what the
    ``aeea_health_check_status`` metric reflects, so a monitoring system can
    alert on trend/history rather than only the instantaneous probe result.

    Returns:
        ``True`` if every check passed.
    """
    db_up = await database.ping()
    HEALTH_CHECK_STATUS.labels(check="database").set(1.0 if db_up else 0.0)
    if not db_up:
        logger.error("health_check_database_down")

    queue_depth = ai_processing_queue.qsize()
    AI_PROCESSING_QUEUE_DEPTH.set(queue_depth)
    queue_ok = queue_depth <= settings.scheduler.ai_processing_queue_warning_depth
    HEALTH_CHECK_STATUS.labels(check="ai_processing_queue").set(
        1.0 if queue_ok else 0.0
    )
    if not queue_ok:
        logger.warning("health_check_ai_processing_queue_deep", depth=queue_depth)

    async with database.session() as session:
        dead_letter_count = await RetryQueueService(
            FailedJobRepository(session)
        ).count_dead_letter()
    dlq_ok = dead_letter_count <= settings.scheduler.dead_letter_queue_warning_depth
    HEALTH_CHECK_STATUS.labels(check="dead_letter_queue").set(1.0 if dlq_ok else 0.0)
    if not dlq_ok:
        logger.warning("health_check_dead_letter_queue_deep", depth=dead_letter_count)

    return db_up and queue_ok and dlq_ok


def build_scheduler(
    *,
    database: Database,
    settings: Settings,
    google_http_client: httpx.AsyncClient,
    event_bus: EventBus,
    ai_processing_queue: AIProcessingQueue,
) -> AsyncIOScheduler:
    """Build (but do not start) the process-wide APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    calendar_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=settings.calendar.requests_per_second,
        burst_capacity=settings.calendar.burst_capacity,
    )
    gmail_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=settings.gmail.requests_per_second,
        burst_capacity=settings.gmail.burst_capacity,
    )

    async def _dispatch_reminders_job() -> None:
        try:
            async with track_job("dispatch_due_reminders"):
                count = await dispatch_due_reminders(
                    database, settings, http_client=google_http_client
                )
                if count:
                    logger.info("reminders_dispatched", count=count)
        except Exception as exc:
            logger.warning("reminder_dispatch_job_failed", error=str(exc))

    async def _sync_calendars_job() -> None:
        try:
            async with track_job("sync_google_calendars"):
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

    async def _poll_gmail_job() -> None:
        try:
            async with track_job("poll_gmail"):
                count = await poll_all_users(
                    database,
                    settings,
                    http_client=google_http_client,
                    rate_limiter=gmail_rate_limiter,
                    event_bus=event_bus,
                    ai_queue=ai_processing_queue,
                )
                if count:
                    logger.info("gmail_poll_completed", messages_processed=count)
        except Exception as exc:
            logger.warning("gmail_poll_job_failed", error=str(exc))

    async def _memory_decay_job() -> None:
        try:
            async with track_job("run_memory_decay_sweep"):
                count = await run_memory_decay_sweep(database)
                logger.info("memory_decay_sweep_completed", rescored=count)
        except Exception as exc:
            logger.warning("memory_decay_job_failed", error=str(exc))

    async def _memory_consolidation_job() -> None:
        try:
            async with track_job("run_memory_consolidation"):
                count = await run_memory_consolidation(database, settings)
                if count:
                    logger.info("memory_consolidation_completed", consolidated=count)
        except Exception as exc:
            logger.warning("memory_consolidation_job_failed", error=str(exc))

    async def _morning_digest_job() -> None:
        try:
            async with track_job("send_morning_digests"):
                count = await send_morning_digests(
                    database, settings, http_client=google_http_client
                )
                logger.info("morning_digests_sent", count=count)
        except Exception as exc:
            logger.warning("morning_digest_job_failed", error=str(exc))

    async def _weekly_digest_job() -> None:
        try:
            async with track_job("send_weekly_digests"):
                count = await send_weekly_digests(
                    database, settings, http_client=google_http_client
                )
                logger.info("weekly_digests_sent", count=count)
        except Exception as exc:
            logger.warning("weekly_digest_job_failed", error=str(exc))

    async def _cleanup_sweep_job() -> None:
        try:
            async with track_job("run_cleanup_sweep"):
                result = await run_cleanup_sweep(database, settings)
                if result.total:
                    logger.info(
                        "cleanup_sweep_completed",
                        sessions=result.expired_sessions_purged,
                        prompt_logs=result.prompt_logs_purged,
                        notifications=result.notifications_purged,
                        retry_jobs=result.resolved_retry_jobs_purged,
                    )
        except Exception as exc:
            logger.warning("cleanup_sweep_job_failed", error=str(exc))

    async def _process_retry_queue_job() -> None:
        try:
            async with track_job("process_retry_queue"):
                count = await process_retry_queue(
                    database,
                    settings,
                    http_client=google_http_client,
                    rate_limiter=gmail_rate_limiter,
                    event_bus=event_bus,
                    ai_queue=ai_processing_queue,
                )
                if count:
                    logger.info("retry_queue_processed", attempts=count)
        except Exception as exc:
            logger.warning("retry_queue_job_failed", error=str(exc))

    async def _health_check_job() -> None:
        try:
            async with track_job("run_health_check_sweep"):
                healthy = await run_health_check_sweep(
                    database, settings, ai_processing_queue=ai_processing_queue
                )
                if not healthy:
                    logger.warning("health_check_sweep_unhealthy")
        except Exception as exc:
            logger.warning("health_check_job_failed", error=str(exc))

    async def _backfill_embeddings_job() -> None:
        try:
            async with track_job("backfill_email_embeddings"):
                count = await backfill_email_embeddings(database, settings)
                if count:
                    logger.info("email_embeddings_backfilled", count=count)
        except Exception as exc:
            logger.warning("email_embedding_backfill_job_failed", error=str(exc))

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
        _poll_gmail_job,
        "interval",
        seconds=settings.scheduler.email_poll_interval_seconds,
        id="poll_gmail",
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
    scheduler.add_job(
        _memory_consolidation_job,
        "interval",
        hours=settings.scheduler.memory_consolidation_interval_hours,
        id="run_memory_consolidation",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _morning_digest_job,
        CronTrigger(
            hour=settings.scheduler.morning_digest_hour_utc,
            minute=settings.scheduler.morning_digest_minute_utc,
            timezone=UTC,
        ),
        id="send_morning_digests",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _weekly_digest_job,
        CronTrigger(
            day_of_week=settings.scheduler.weekly_digest_weekday,
            hour=settings.scheduler.weekly_digest_hour_utc,
            minute=settings.scheduler.weekly_digest_minute_utc,
            timezone=UTC,
        ),
        id="send_weekly_digests",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _cleanup_sweep_job,
        "interval",
        hours=settings.scheduler.cleanup_interval_hours,
        id="run_cleanup_sweep",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _process_retry_queue_job,
        "interval",
        seconds=settings.scheduler.retry_queue_interval_seconds,
        id="process_retry_queue",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _health_check_job,
        "interval",
        seconds=settings.scheduler.health_check_interval_seconds,
        id="run_health_check_sweep",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _backfill_embeddings_job,
        "interval",
        seconds=settings.scheduler.email_embedding_backfill_interval_seconds,
        id="backfill_email_embeddings",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
