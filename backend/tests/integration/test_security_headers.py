"""Integration tests for the security-headers middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_security_headers_present_on_every_response(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-XSS-Protection"] == "1; mode=block"


@pytest.mark.asyncio
async def test_hsts_is_absent_outside_production(client: AsyncClient) -> None:
    # The shared test `settings` fixture uses environment="test" -- HSTS
    # over what could be a plain-HTTP deployment would be actively wrong.
    response = await client.get("/api/v1/health/live")
    assert "Strict-Transport-Security" not in response.headers


@pytest.mark.asyncio
async def test_security_headers_present_on_error_responses_too(
    client: AsyncClient,
) -> None:
    # Security headers are the outermost middleware layer -- they must
    # wrap even a 401/404/429, not just the happy path.
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["X-Frame-Options"] == "DENY"
