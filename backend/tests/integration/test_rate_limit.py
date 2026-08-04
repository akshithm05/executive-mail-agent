"""Integration tests for the inbound rate-limiting middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.config.settings import AISettings, RateLimitSettings, SessionSettings, Settings
from app.infra.db.session import Database
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.main import create_app
from httpx import ASGITransport, AsyncClient

from tests.fake_anthropic.app import create_fake_anthropic_app
from tests.fake_google.app import create_fake_google_app
from tests.fake_redis import FakeRedis


@pytest_asyncio.fixture
async def rate_limited_client(database: Database) -> AsyncIterator[AsyncClient]:
    """A client whose app enforces a tiny (3 requests / 60s) rate-limit budget."""
    settings = Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        session=SessionSettings(cookie_secure=False),
        ai=AISettings(anthropic_api_key="test-key"),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=3, window_seconds=60
        ),
    )
    application = create_app(settings)
    application.state.db = database
    application.state.redis = FakeRedis()
    application.state.gmail_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=1000.0, burst_capacity=1000
    )

    async with (
        AsyncClient(
            transport=ASGITransport(app=create_fake_google_app())
        ) as google_http_client,
        AsyncClient(
            transport=ASGITransport(app=create_fake_anthropic_app())
        ) as anthropic_http_client,
    ):
        application.state.google_http_client = google_http_client
        application.state.anthropic_http_client = anthropic_http_client
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_requests_within_budget_succeed(
    rate_limited_client: AsyncClient,
) -> None:
    for _ in range(3):
        response = await rate_limited_client.get("/api/v1/auth/me")
        assert response.status_code in (
            401,
            200,
        )  # not authenticated, but not rate-limited


@pytest.mark.asyncio
async def test_requests_beyond_budget_are_rejected_with_429(
    rate_limited_client: AsyncClient,
) -> None:
    for _ in range(3):
        await rate_limited_client.get("/api/v1/auth/me")

    response = await rate_limited_client.get("/api/v1/auth/me")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_health_and_metrics_are_exempt_from_rate_limiting(
    rate_limited_client: AsyncClient,
) -> None:
    for _ in range(10):
        response = await rate_limited_client.get("/api/v1/health/live")
        assert response.status_code == 200
