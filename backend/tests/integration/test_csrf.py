"""Integration tests for the double-submit-cookie CSRF middleware."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from app.config.settings import Settings
from httpx import AsyncClient

from tests.fake_google.app import VALID_AUTH_CODE


async def _login_without_csrf_header(client: AsyncClient) -> None:
    """Complete login (issuing session + CSRF cookies) without echoing the header."""
    login_response = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": state},
    )
    assert callback_response.status_code == 200


@pytest.mark.asyncio
async def test_mutating_request_without_csrf_header_is_rejected(
    client: AsyncClient,
) -> None:
    await _login_without_csrf_header(client)
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_check_failed"


@pytest.mark.asyncio
async def test_mutating_request_with_wrong_csrf_header_is_rejected(
    client: AsyncClient, settings: Settings
) -> None:
    await _login_without_csrf_header(client)
    client.headers[settings.csrf.header_name] = "not-the-right-token"
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mutating_request_with_correct_csrf_header_succeeds(
    client: AsyncClient, settings: Settings
) -> None:
    await _login_without_csrf_header(client)
    csrf_token = client.cookies.get(settings.csrf.cookie_name)
    assert csrf_token is not None
    client.headers[settings.csrf.header_name] = csrf_token

    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_requests_are_never_csrf_checked(client: AsyncClient) -> None:
    await _login_without_csrf_header(client)
    # No CSRF header set, but GET is a safe method -- must not 403.
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unauthenticated_mutating_request_is_not_csrf_checked(
    client: AsyncClient,
) -> None:
    # No session cookie at all -- the request should fail on authentication,
    # not CSRF (there's no ambient authority yet to protect).
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401
