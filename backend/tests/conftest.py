"""Shared pytest fixtures.

Tests run against an isolated, file-backed SQLite database created per test so
they are fast, hermetic, and require no external Postgres. The FastAPI app is
built with test settings and has its ``app.state.db`` pointed at the test
database, bypassing the production lifespan.

Google OAuth/Gmail calls are routed to an in-process fake server (see
``tests/fake_google/app.py``) via a swapped ``httpx.ASGITransport`` -- real
HTTP request/response cycles against real route handlers, not
``unittest.mock`` stubs standing in for our own code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import app.infra.models
import pytest
import pytest_asyncio
from app.config.settings import AISettings, RateLimitSettings, SessionSettings, Settings
from app.infra.db.base import Base
from app.infra.db.session import Database
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.main import create_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.fake_anthropic.app import create_fake_anthropic_app
from tests.fake_google.app import (
    VALID_AUTH_CODE,
    FakeGoogleState,
    create_fake_google_app,
)
from tests.fake_redis import FakeRedis


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """Provide a fresh SQLite-backed :class:`Database` with tables created."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
def settings() -> Settings:
    """Return settings configured for the test environment.

    ``session.cookie_secure=False`` is required for the session cookie to
    round-trip through httpx's cookie jar in tests, which talk to the ASGI
    app over a plain ``http://`` base URL (the same is true of any local,
    non-TLS deployment -- see ``SESSION_COOKIE_SECURE`` in ``.env.example``).

    Rate limiting is disabled by default -- CSRF is deliberately left
    enabled (see ``logged_in_client``, which handles it transparently) since
    that's real, always-on protection every mutating-request test already
    exercises, but a shared 120-req/window budget across every test in the
    suite (which don't run in isolated processes) would be an unrelated
    source of flakiness. Tests that specifically exercise rate limiting
    build their own ``Settings(rate_limit=RateLimitSettings(enabled=True))``.
    """
    return Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        session=SessionSettings(cookie_secure=False),
        ai=AISettings(anthropic_api_key="test-key"),
        rate_limit=RateLimitSettings(enabled=False),
    )


@pytest.fixture
def fake_google_app() -> FastAPI:
    """Provide a fresh fake Google/Gmail ASGI app with isolated in-memory state."""
    return create_fake_google_app()


@pytest.fixture
def fake_google_state(fake_google_app: FastAPI) -> FakeGoogleState:
    """Expose the fake server's mutable state for tests to inspect/manipulate.

    E.g. simulating the user revoking Gmail access from their Google account
    (rather than our app calling logout) to exercise the reauthentication path.
    """
    state: FakeGoogleState = fake_google_app.state.fake_google
    return state


@pytest_asyncio.fixture
async def fake_google_http_client(
    fake_google_app: FastAPI,
) -> AsyncIterator[AsyncClient]:
    """Provide an HTTP client whose transport is the fake Google/Gmail ASGI app."""
    transport = ASGITransport(app=fake_google_app)
    async with AsyncClient(transport=transport) as client:
        yield client


@pytest_asyncio.fixture
async def fake_anthropic_http_client() -> AsyncIterator[AsyncClient]:
    """Provide an HTTP client whose transport is the fake Anthropic ASGI app.

    Wired into ``app.state.anthropic_http_client`` so any route depending on
    ``StructuredLLMClientDep`` (see ``app/api/deps.py``) talks to the fake
    server instead of the real Anthropic API.
    """
    transport = ASGITransport(app=create_fake_anthropic_app())
    async with AsyncClient(transport=transport) as client:
        yield client


@pytest.fixture
def app(
    settings: Settings,
    database: Database,
    fake_google_http_client: AsyncClient,
    fake_anthropic_http_client: AsyncClient,
):
    """Build a FastAPI app wired to the test database and fake external servers."""
    application = create_app(settings)
    application.state.db = database
    application.state.google_http_client = fake_google_http_client
    application.state.anthropic_http_client = fake_anthropic_http_client
    application.state.gmail_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=1000.0, burst_capacity=1000
    )
    # The real lifespan (app/main.py's _build_lifespan) never runs in tests
    # -- httpx's ASGITransport doesn't trigger FastAPI startup/shutdown
    # events -- so every piece of state it would normally set up on
    # app.state is instead set here directly. Redis is no exception: a
    # real in-memory fake (see tests/fake_redis.py), not a real server,
    # keeping the suite hermetic.
    application.state.redis = FakeRedis()
    return application


@pytest_asyncio.fixture
async def client(app: object) -> AsyncIterator[AsyncClient]:
    """Provide an httpx client bound to the ASGI app."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def logged_in_client(client: AsyncClient, settings: Settings) -> AsyncClient:
    """An httpx client that has completed a real Google login round-trip.

    Drives the actual ``/auth/google/login`` -> ``/auth/google/callback``
    sequence (which in turn calls the fake Google server), so the resulting
    session cookie is the product of real application code, not injected
    directly into the client's cookie jar.

    Also echoes the double-submit CSRF cookie the callback issues (see
    ``app/api/v1/routes/auth.py``'s ``_set_csrf_cookie``) back as a default
    header on every subsequent request from this client -- exactly what a
    real frontend does (read the JS-readable cookie, send it as a header on
    mutating requests) -- so every existing test that POSTs/PATCHes/DELETEs
    through this fixture keeps passing the CSRF check in ``app/api/
    middleware/csrf.py`` without each test needing to know CSRF exists.
    """
    login_response = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    location = login_response.headers["location"]
    state = parse_qs(urlparse(location).query)["state"][0]
    callback_response = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": state},
    )
    assert callback_response.status_code == 200
    csrf_token = client.cookies.get(settings.csrf.cookie_name)
    assert csrf_token is not None
    client.headers[settings.csrf.header_name] = csrf_token
    return client
