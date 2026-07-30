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

from app import __version__
from app.agents.email_agent import run_email_triage
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestLoggingMiddleware
from app.api.v1.router import api_router
from app.config.logging import configure_logging, get_logger
from app.config.settings import Settings, get_settings
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.scheduler import build_scheduler
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

        google_http_client = httpx.AsyncClient()
        app.state.google_http_client = google_http_client
        app.state.gmail_rate_limiter = TokenBucketRateLimiter(
            rate_per_second=settings.gmail.requests_per_second,
            burst_capacity=settings.gmail.burst_capacity,
        )

        async def ai_processor(job: AIProcessingJob) -> None:
            await run_email_triage(job, database, settings)

        app.state.event_bus = EventBus()
        app.state.ai_processing_queue = AIProcessingQueue()
        ai_worker = AIProcessingWorker(
            app.state.ai_processing_queue, processor=ai_processor
        )
        ai_worker.start()
        app.state.ai_processing_worker = ai_worker

        if not settings.ai.is_configured:
            logger.warning("ai_agent_not_configured")

        if not settings.oauth.is_configured:
            logger.warning("oauth_not_configured")

        scheduler = build_scheduler(
            database=database, settings=settings, google_http_client=google_http_client
        )
        scheduler.start()
        app.state.scheduler = scheduler

        logger.info("application_started")
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await ai_worker.stop()
            await google_http_client.aclose()
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

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=_build_lifespan(settings),
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware (outermost first): CORS wraps request logging.
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

    register_exception_handlers(app)
    app.state.settings = settings
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


# ASGI entrypoint used by uvicorn/gunicorn: ``uvicorn app.main:app``.
app = create_app()
