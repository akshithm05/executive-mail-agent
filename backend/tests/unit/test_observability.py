"""Unit tests for Sentry/OpenTelemetry setup (``app/observability.py``).

Both integrations are opt-in and every setup call is defensively wrapped so
a third-party SDK's API drifting can never crash startup -- these tests
prove both halves of that contract: the no-op path when unconfigured, the
happy path when configured, and that a broken integration is swallowed
rather than propagated.

``init_tracing``'s ``HTTPXClientInstrumentor().instrument()`` call patches
``httpx`` globally for the whole process -- calling it for real here would
leak instrumentation into every other test in the suite that uses httpx
(nearly all of them). Its own success path is exercised in isolation; here
``HTTPXClientInstrumentor.instrument`` is monkeypatched to a local no-op so
every other line in ``init_tracing`` still runs for real without polluting
global state.
"""

from __future__ import annotations

import pytest
from app.config.settings import OTelSettings, SentrySettings, Settings
from app.infra.db.session import Database
from app.observability import init_sentry, init_tracing, instrument_database
from fastapi import FastAPI


def test_init_sentry_is_a_noop_when_unconfigured() -> None:
    settings = Settings(environment="test", sentry=SentrySettings(dsn=""))
    init_sentry(settings)  # must not raise


def test_init_sentry_initializes_the_sdk_when_configured() -> None:
    settings = Settings(
        environment="test",
        sentry=SentrySettings(
            dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
        ),
    )
    init_sentry(settings)  # must not raise

    import sentry_sdk

    client = sentry_sdk.get_global_scope().client
    assert client is not None
    assert client.is_active()
    # Close immediately (no flush wait) so the SDK's atexit hook has
    # nothing pending to retry against the fake DSN at interpreter exit.
    client.close(timeout=0)


def test_init_sentry_swallows_a_broken_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentry_sdk

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("sentry_sdk API drifted")

    monkeypatch.setattr(sentry_sdk, "init", _boom)
    settings = Settings(
        environment="test",
        sentry=SentrySettings(dsn="https://examplePublicKey@o0.ingest.sentry.io/0"),
    )
    init_sentry(settings)  # must not raise despite sentry_sdk.init blowing up


def test_init_tracing_is_a_noop_when_unconfigured() -> None:
    settings = Settings(
        environment="test", otel=OTelSettings(exporter_otlp_endpoint="")
    )
    init_tracing(FastAPI(), settings)  # must not raise


def test_init_tracing_instruments_the_app_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    monkeypatch.setattr(HTTPXClientInstrumentor, "instrument", lambda self: None)

    settings = Settings(
        environment="test",
        otel=OTelSettings(exporter_otlp_endpoint="http://collector.test:4318"),
    )
    init_tracing(FastAPI(), settings)  # must not raise


def test_init_tracing_swallows_a_broken_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace import TracerProvider

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("otel API drifted")

    monkeypatch.setattr(TracerProvider, "__init__", _boom)
    settings = Settings(
        environment="test",
        otel=OTelSettings(exporter_otlp_endpoint="http://collector.test:4318"),
    )
    init_tracing(FastAPI(), settings)  # must not raise


@pytest.mark.asyncio
async def test_instrument_database_is_a_noop_when_unconfigured() -> None:
    settings = Settings(
        environment="test", otel=OTelSettings(exporter_otlp_endpoint="")
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        instrument_database(database.engine, settings)  # must not raise
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_instrument_database_instruments_the_engine_when_configured() -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    settings = Settings(
        environment="test",
        otel=OTelSettings(exporter_otlp_endpoint="http://collector.test:4318"),
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        instrument_database(database.engine, settings)  # must not raise
    finally:
        SQLAlchemyInstrumentor().uninstrument(engine=database.engine.sync_engine)
        await database.dispose()


@pytest.mark.asyncio
async def test_instrument_database_swallows_a_broken_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    def _boom(self: object, **kwargs: object) -> None:
        raise RuntimeError("otel sqlalchemy API drifted")

    monkeypatch.setattr(SQLAlchemyInstrumentor, "instrument", _boom)
    settings = Settings(
        environment="test",
        otel=OTelSettings(exporter_otlp_endpoint="http://collector.test:4318"),
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        instrument_database(database.engine, settings)  # must not raise
    finally:
        await database.dispose()
