"""Integration tests for the Google login/logout/refresh lifecycle.

These drive the real ``/api/v1/auth/*`` routes over HTTP (via the ``client``
fixture), which in turn call the real ``GoogleAuthService`` and
``GoogleOAuthClient``, which in turn make real HTTP calls to the fake Google
server (``tests/fake_google``) instead of ``unittest.mock`` stand-ins.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL, VALID_AUTH_CODE, FakeGoogleState


@pytest.mark.asyncio
async def test_login_redirects_to_google_with_state_cookie(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/google/login", follow_redirects=False)

    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    params = parse_qs(location.query)
    assert params["response_type"] == ["code"]
    assert "state" in params
    assert client.cookies.get("aeea_oauth_state") == params["state"][0]


@pytest.mark.asyncio
async def test_callback_completes_login_and_sets_session_cookie(
    client: AsyncClient,
) -> None:
    login_response = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    callback_response = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": state},
    )

    assert callback_response.status_code == 200
    body = callback_response.json()
    assert body["email"] == USER_EMAIL
    assert client.cookies.get("aeea_session") is not None

    me_response = await client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == USER_EMAIL


@pytest.mark.asyncio
async def test_callback_rejects_missing_or_mismatched_state(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": "not-the-cookie-value"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "oauth_callback_failed"


@pytest.mark.asyncio
async def test_callback_rejects_invalid_authorization_code(client: AsyncClient) -> None:
    login_response = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    response = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "not-a-real-code", "state": state},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "oauth_callback_failed"


@pytest.mark.asyncio
async def test_callback_rejects_reused_authorization_code(client: AsyncClient) -> None:
    login_response = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    first = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": state},
    )
    assert first.status_code == 200

    # Reuse the same code/state pair -- Google rejects a consumed code.
    login_response_2 = await client.get(
        "/api/v1/auth/google/login", follow_redirects=False
    )
    state_2 = parse_qs(urlparse(login_response_2.headers["location"]).query)["state"][0]
    second = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": VALID_AUTH_CODE, "state": state_2},
    )

    assert second.status_code == 400
    assert second.json()["code"] == "oauth_callback_failed"


@pytest.mark.asyncio
async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_refresh_forces_new_access_token(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert response.json()["status"] == "refreshed"


@pytest.mark.asyncio
async def test_refresh_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_surfaces_reauthentication_when_grant_revoked(
    logged_in_client: AsyncClient, fake_google_state: FakeGoogleState
) -> None:
    # Simulate the user revoking Gmail access from their Google account
    # settings -- Google will now reject any refresh with invalid_grant.
    fake_google_state.revoked_tokens.update(fake_google_state.refresh_tokens.keys())

    response = await logged_in_client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["code"] == "reauthentication_required"


@pytest.mark.asyncio
async def test_logout_revokes_session(logged_in_client: AsyncClient) -> None:
    logout_response = await logged_in_client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["status"] == "logged_out"

    me_response = await logged_in_client.get("/api/v1/auth/me")
    assert me_response.status_code == 401


@pytest.mark.asyncio
async def test_logout_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 401
