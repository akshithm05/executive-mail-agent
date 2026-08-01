"""Sentry error tracking and OpenTelemetry distributed tracing setup.

Both are entirely opt-in via settings (``SentrySettings.dsn`` /
``OTelSettings.exporter_otlp_endpoint``) -- unconfigured, both are no-ops,
matching the graceful-degradation convention used everywhere else in this
codebase (e.g. ``AISettings.is_configured``). Every setup call is also
wrapped defensively: these are optional observability integrations, and a
third-party SDK's API drifting between versions must never be able to
crash application startup.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.logging import get_logger
from app.config.settings import Settings

logger = get_logger(__name__)


def init_sentry(settings: Settings) -> None:
    """Initialize Sentry error tracking, if ``SENTRY_DSN`` is configured."""
    if not settings.sentry.is_configured:
        logger.info("sentry_not_configured")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry.dsn,
            environment=settings.environment,
            release=settings.git_sha,
            traces_sample_rate=settings.sentry.traces_sample_rate,
            profiles_sample_rate=settings.sentry.profiles_sample_rate,
            integrations=[StarletteIntegration(), FastApiIntegration()],
        )
        logger.info("sentry_configured", environment=settings.environment)
    except Exception:
        logger.exception("sentry_init_failed")


def init_tracing(app: Any, settings: Settings) -> None:
    """Initialize OpenTelemetry tracing + FastAPI/httpx auto-instrumentation.

    A no-op if ``OTEL_EXPORTER_OTLP_ENDPOINT`` isn't set. Call once, after
    the FastAPI app is fully constructed.
    """
    if not settings.otel.is_configured:
        logger.info("otel_not_configured")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({SERVICE_NAME: settings.otel.service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel.exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        logger.info("otel_configured", endpoint=settings.otel.exporter_otlp_endpoint)
    except Exception:
        logger.exception("otel_init_failed")


def instrument_database(engine: AsyncEngine, settings: Settings) -> None:
    """Instrument a SQLAlchemy engine for OpenTelemetry, if tracing is enabled."""
    if not settings.otel.is_configured:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except Exception:
        logger.exception("otel_sqlalchemy_instrumentation_failed")
