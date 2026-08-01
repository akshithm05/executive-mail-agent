"""FastAPI application factory.

This module is the composition root: it wires configuration, logging,
middleware, exception handlers, routers, and the database lifecycle into a
single :class:`FastAPI` instance. Keeping construction in a factory
(:func:`create_app`) rather than at import time lets tests build isolated app
instances with overridden dependencies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.agents.email_agent import run_email_triage
from app.api.errors import register_exception_handlers
from app.api.middleware import (
    CSRFMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.v1.router import api_router
from app.config.logging import configure_logging, get_logger
from app.config.settings import Settings, get_settings
from app.infra.cache import build_redis_client
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.leader_lock import try_acquire_scheduler_leadership
from app.infra.metrics import AI_TRIAGE_TOTAL
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.infra.repositories.failed_job import FailedJobRepository
from app.observability import init_sentry, init_tracing, instrument_database
from app.scheduler import build_scheduler
from app.services.retry_queue import RetryQueueService
from app.workers.ai_processing_worker import AIProcessingWorker

logger = get_logger(__name__)


def _build_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create a lifespan context manager bound to the given settings.

    The lifespan opens the database connection pool on startup and disposes of
    it on shutdown, guaranteeing clean resource management even if startup
    partially fails.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application_starting",
            environment=settings.environment,
            version=__version__,
        )
        database = Database(
            settings.database.async_dsn,
            echo=settings.database.echo,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_pre_ping=settings.database.pool_pre_ping,
        )
        app.state.db = database
        instrument_database(database.engine, settings)

        redis_client = build_redis_client(settings.redis)
        app.state.redis = redis_client
        try:
            await redis_client.ping()
        except Exception as exc:
            # Fail open, not closed: caching and rate limiting both degrade
            # gracefully without Redis (see app/infra/cache.py's module
            # docstring) -- this is a loud warning, not a startup failure.
            logger.warning("redis_unreachable_at_startup", error=str(exc))

        google_http_client = httpx.AsyncClient()
        app.state.google_http_client = google_http_client
        app.state.gmail_rate_limiter = TokenBucketRateLimiter(
            rate_per_second=settings.gmail.requests_per_second,
            burst_capacity=settings.gmail.burst_capacity,
        )

        async def ai_processor(job: AIProcessingJob) -> None:
            await run_email_triage(job, database, settings)

        async def ai_processing_failed(
            job: AIProcessingJob, error: BaseException
        ) -> None:
            """Push a permanently-failed triage job onto the retry queue.

            The AI-processing worker already retried this job in-process
            (see ``AIProcessingWorker``); this only fires once that has been
            exhausted, so the failure is still visible and retryable later
            instead of being silently dropped.
            """
            AI_TRIAGE_TOTAL.labels(outcome="failure").inc()
            async with database.session() as session:
                retry_queue = RetryQueueService(FailedJobRepository(session))
                await retry_queue.enqueue_failure(
                    tenant_id=job.tenant_id,
                    user_id=job.user_id,
                    job_type="ai_triage",
                    payload={
                        "tenant_id": str(job.tenant_id),
                        "user_id": str(job.user_id),
                        "email_id": str(job.email_id),
                        "gmail_message_id": job.gmail_message_id,
                    },
                    error=error,
                )

        app.state.event_bus = EventBus()
        app.state.ai_processing_queue = AIProcessingQueue()
        ai_worker = AIProcessingWorker(
            app.state.ai_processing_queue,
            processor=ai_processor,
            on_failure=ai_processing_failed,
        )
        ai_worker.start()
        app.state.ai_processing_worker = ai_worker

        if not settings.ai.is_configured:
            logger.warning("ai_agent_not_configured")

        if not settings.oauth.is_configured:
            logger.warning("oauth_not_configured")

        scheduler = build_scheduler(
            database=database,
            settings=settings,
            google_http_client=google_http_client,
            event_bus=app.state.event_bus,
            ai_processing_queue=app.state.ai_processing_queue,
        )
        # Only one replica's scheduler should actually fire jobs -- see
        # app/infra/leader_lock.py's module docstring.
        is_scheduler_leader = await try_acquire_scheduler_leadership(redis_client)
        if is_scheduler_leader:
            scheduler.start()
        app.state.scheduler = scheduler

        logger.info("application_started")
        try:
            yield
        finally:
            if is_scheduler_leader:
                scheduler.shutdown(wait=False)
            await ai_worker.stop()
            await google_http_client.aclose()
            await redis_client.aclose()
            await database.dispose()
            logger.info("application_stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure a :class:`FastAPI` application.

    Args:
        settings: Optional settings override; defaults to the process
            singleton. Tests pass a custom instance to isolate configuration.

    Returns:
        A fully wired FastAPI application ready to serve requests.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    init_sentry(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=_build_lifespan(settings),
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware, added innermost-first (each subsequent call wraps the
    # ones before it, so the last one added is the outermost layer -- see
    # each middleware's own docstring for why it sits where it does):
    #   CSRF -> RateLimit -> RequestLogging -> CORS -> GZip -> SecurityHeaders
    app.add_middleware(CSRFMiddleware, session_cookie_name=settings.session.cookie_name)
    app.add_middleware(
        RateLimitMiddleware, session_cookie_name=settings.session.cookie_name
    )
    app.add_middleware(
        RequestLoggingMiddleware,
        header_name=settings.request_id_header,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.is_production)

    register_exception_handlers(app)
    app.state.settings = settings
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    init_tracing(app, settings)

    return app


# ASGI entrypoint used by uvicorn/gunicorn: ``uvicorn app.main:app``.
app = create_app()
