"""Google OAuth 2.0 / OpenID Connect HTTP client.

Implements the network calls Phase 2 needs against Google's OAuth
endpoints: authorization-code exchange, refresh-token exchange, identity
(userinfo) lookup, and token revocation for logout. Retries and rate-limit
handling are delegated to :mod:`app.infra.google.http`.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.logging import get_logger
from app.config.settings import OAuthSettings
from app.core.exceptions import OAuthCallbackError, ReauthenticationRequiredError
from app.infra.google.http import send_with_retry
from app.infra.google.types import GoogleTokenResponse, GoogleUserInfo

logger = get_logger(__name__)

_MAX_ATTEMPTS = 3


class GoogleOAuthClient:
    """Talks to Google's OAuth 2.0 and OpenID Connect endpoints."""

    def __init__(self, http_client: httpx.AsyncClient, settings: OAuthSettings) -> None:
        self._http = http_client
        self._settings = settings

    async def exchange_code(self, code: str) -> GoogleTokenResponse:
        """Exchange an authorization code for access + refresh tokens.

        Raises:
            OAuthCallbackError: The code is invalid, expired, or already used.
        """
        response = await send_with_retry(
            self._http,
            "POST",
            self._settings.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "redirect_uri": self._settings.redirect_uri,
            },
            max_attempts=_MAX_ATTEMPTS,
        )
        if response.status_code >= 400:
            logger.warning(
                "oauth_code_exchange_failed", status_code=response.status_code
            )
            raise OAuthCallbackError(detail=_safe_error_body(response))
        return _parse_token_response(response.json())

    async def refresh_access_token(self, refresh_token: str) -> GoogleTokenResponse:
        """Exchange a refresh token for a new access token.

        Raises:
            ReauthenticationRequiredError: Google rejected the refresh token
                (revoked, expired, or the grant was invalidated -- e.g. the
                user changed their Google password or removed app access).
        """
        response = await send_with_retry(
            self._http,
            "POST",
            self._settings.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
            },
            max_attempts=_MAX_ATTEMPTS,
        )
        if response.status_code >= 400:
            logger.info("oauth_refresh_failed", status_code=response.status_code)
            raise ReauthenticationRequiredError()
        return _parse_token_response(response.json())

    async def fetch_userinfo(self, access_token: str) -> GoogleUserInfo:
        """Fetch the authenticated user's Google identity."""
        response = await send_with_retry(
            self._http,
            "GET",
            self._settings.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            max_attempts=_MAX_ATTEMPTS,
        )
        if response.status_code >= 400:
            raise OAuthCallbackError(detail=_safe_error_body(response))
        body: dict[str, Any] = response.json()
        return GoogleUserInfo(
            sub=str(body["sub"]),
            email=str(body.get("email", "")),
            email_verified=bool(body.get("email_verified", False)),
            name=str(body.get("name", "")),
            picture=str(body.get("picture", "")),
        )

    async def revoke(self, token: str) -> None:
        """Revoke an access or refresh token at Google.

        Best-effort: failures are logged but not raised, since local logout
        (clearing our own session/credential) must succeed even if Google's
        revoke endpoint is unreachable.
        """
        try:
            response = await send_with_retry(
                self._http,
                "POST",
                self._settings.revoke_url,
                data={"token": token},
                max_attempts=_MAX_ATTEMPTS,
            )
        except Exception:
            logger.warning("oauth_revoke_failed", exc_info=True)
            return
        if response.status_code >= 400:
            logger.warning("oauth_revoke_rejected", status_code=response.status_code)


def _parse_token_response(body: dict[str, Any]) -> GoogleTokenResponse:
    return GoogleTokenResponse(
        access_token=str(body["access_token"]),
        expires_in=int(body["expires_in"]),
        scope=str(body.get("scope", "")),
        token_type=str(body.get("token_type", "Bearer")),
        refresh_token=body.get("refresh_token"),
        id_token=body.get("id_token"),
    )


def _safe_error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        result: dict[str, Any] = response.json()
        return result
    except ValueError:
        return {"raw": response.text[:500]}
