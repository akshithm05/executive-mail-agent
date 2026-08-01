"""Integration tests for the ``GET /api/v1/emails/search`` endpoint."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from app.agents.embeddings import HashingEmbeddingProvider
from app.config.settings import AISettings, SessionSettings, Settings
from app.infra.db.session import Database
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.email import Email
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.user import UserRepository
from app.main import create_app
from httpx import ASGITransport, AsyncClient

from tests.fake_anthropic.app import create_fake_anthropic_app
from tests.fake_google.app import USER_EMAIL, VALID_AUTH_CODE, create_fake_google_app

_EMBEDDER = HashingEmbeddingProvider(dimensions=64)


@pytest.mark.asyncio
async def test_search_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/emails/search", params={"q": "invoices"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_requires_a_query(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get("/api/v1/emails/search")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_returns_paginated_ranked_results(
    logged_in_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        subject = "Recruiter reaching out about a new role"
        embedding = _EMBEDDER.embed(subject)
        await EmailRepository(session).add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="msg-1",
                gmail_thread_id="thread-1",
                subject=subject,
                from_address="recruiter@example.com",
                received_at=datetime.now(UTC),
                embedding=embedding,
                embedding_model=_EMBEDDER.model_name,
            )
        )

    response = await logged_in_client.get(
        "/api/v1/emails/search", params={"q": "recruiter emails", "limit": 5}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "recruiter emails"
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert body["total"] >= 1
    assert any(hit["email"]["subject"] == subject for hit in body["results"])
    assert all("score" in hit for hit in body["results"])


@pytest_asyncio.fixture
async def ai_unconfigured_client(
    database: Database,
) -> AsyncIterator[AsyncClient]:
    """A logged-in client whose app has no AI configured (heuristic search path)."""
    settings = Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        session=SessionSettings(cookie_secure=False),
        ai=AISettings(anthropic_api_key=""),
    )
    application = create_app(settings)
    application.state.db = database

    fake_google_app = create_fake_google_app()
    async with (
        AsyncClient(transport=ASGITransport(app=fake_google_app)) as google_http_client,
        AsyncClient(
            transport=ASGITransport(app=create_fake_anthropic_app())
        ) as anthropic_http_client,
    ):
        application.state.google_http_client = google_http_client
        application.state.anthropic_http_client = anthropic_http_client
        application.state.gmail_rate_limiter = TokenBucketRateLimiter(
            rate_per_second=1000.0, burst_capacity=1000
        )

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_response = await client.get(
                "/api/v1/auth/google/login", follow_redirects=False
            )
            state = parse_qs(urlparse(login_response.headers["location"]).query)[
                "state"
            ][0]
            callback_response = await client.get(
                "/api/v1/auth/google/callback",
                params={"code": VALID_AUTH_CODE, "state": state},
            )
            assert callback_response.status_code == 200
            yield client


@pytest.mark.asyncio
async def test_search_uses_heuristic_filters_when_ai_not_configured(
    ai_unconfigured_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        repo = EmailRepository(session)
        await repo.add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id=f"unread-{uuid.uuid4().hex[:8]}",
                gmail_thread_id="thread-unread",
                subject="Invoice due",
                from_address="billing@example.com",
                is_read=False,
                received_at=datetime.now(UTC),
            )
        )
        await repo.add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id=f"read-{uuid.uuid4().hex[:8]}",
                gmail_thread_id="thread-read",
                subject="Invoice paid",
                from_address="billing@example.com",
                is_read=True,
                received_at=datetime.now(UTC),
            )
        )

    response = await ai_unconfigured_client.get(
        "/api/v1/emails/search", params={"q": "Unread invoices"}
    )
    assert response.status_code == 200
    body = response.json()
    subjects = [hit["email"]["subject"] for hit in body["results"]]
    assert "Invoice due" in subjects
    assert "Invoice paid" not in subjects
