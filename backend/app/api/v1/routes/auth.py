"""Google authentication endpoints: login, callback, logout, refresh, profile.

Implements the full OAuth 2.0 login lifecycle against Google:

* ``GET /auth/google/login`` -- redirects to Google's consent screen with a
  CSRF ``state`` nonce stashed in a short-lived cookie.
* ``GET /auth/google/callback`` -- validates the returned ``state``, exchanges
  the authorization ``code`` for tokens, provisions/updates the local user,
  and issues a first-party session cookie.
* ``GET /auth/me`` -- returns the signed-in user's profile.
* ``POST /auth/refresh`` -- forces an immediate Google access-token refresh.
* ``POST /auth/logout`` -- revokes the local session and best-effort revokes
  the Google grant.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUserDep, GoogleAuthServiceDep, SettingsDep
from app.core.exceptions import OAuthCallbackError
from app.infra.models.user import User
from app.schemas.auth import LogoutResponse, TokenRefreshResponse, UserProfileResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_OAUTH_STATE_COOKIE = "aeea_oauth_state"
_OAUTH_STATE_TTL_SECONDS = 600


def _set_session_cookie(response: Response, settings: SettingsDep, token: str) -> None:
    response.set_cookie(
        settings.session.cookie_name,
        token,
        max_age=settings.session.ttl_seconds,
        httponly=True,
        secure=settings.session.cookie_secure,
        samesite=settings.session.cookie_samesite,
        path="/",
    )


def _user_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
    )


@router.get(
    "/google/login",
    summary="Start Google sign-in",
    response_class=RedirectResponse,
)
async def google_login(
    auth_service: GoogleAuthServiceDep, settings: SettingsDep
) -> RedirectResponse:
    """Redirect the browser to Google's OAuth 2.0 consent screen."""
    state = auth_service.generate_state()
    authorization_url = auth_service.build_authorization_url(state=state)
    response = RedirectResponse(
        url=authorization_url, status_code=status.HTTP_302_FOUND
    )
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.session.cookie_secure,
        samesite=settings.session.cookie_samesite,
        path="/",
    )
    return response


@router.get("/google/callback", summary="Complete Google sign-in")
async def google_callback(
    request: Request,
    auth_service: GoogleAuthServiceDep,
    settings: SettingsDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    """Handle Google's redirect back after the user grants or denies consent.

    Raises:
        OAuthCallbackError: The user denied consent, the ``state`` is
            missing/mismatched (CSRF check failed), or Google rejected the
            authorization code.
    """
    if error is not None:
        raise OAuthCallbackError(detail={"google_error": error})
    if code is None or state is None:
        raise OAuthCallbackError(detail={"reason": "missing_code_or_state"})

    expected_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise OAuthCallbackError(detail={"reason": "state_mismatch"})

    user = await auth_service.complete_login(code=code)
    session_token = await auth_service.create_session(user)

    response: Response
    if settings.session.post_login_redirect_url:
        response = RedirectResponse(
            url=settings.session.post_login_redirect_url,
            status_code=status.HTTP_302_FOUND,
        )
    else:
        response = Response(
            content=_user_profile(user).model_dump_json(),
            media_type="application/json",
        )

    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    _set_session_cookie(response, settings, session_token)
    return response


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get the signed-in user's profile",
)
async def get_my_profile(user: CurrentUserDep) -> UserProfileResponse:
    """Return the signed-in user's own profile."""
    return _user_profile(user)


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="Force-refresh the Google access token",
)
async def refresh_token(
    user: CurrentUserDep,
    auth_service: GoogleAuthServiceDep,
) -> TokenRefreshResponse:
    """Force an immediate refresh of the user's Google access token.

    Ordinary Gmail API calls refresh lazily, only once the cached token is
    close to expiry (see :meth:`GoogleAuthService.get_valid_access_token`).
    This endpoint eagerly rotates the token on demand -- e.g. to confirm the
    credential is still valid right after linking a mailbox.

    Raises:
        ReauthenticationRequiredError: The stored refresh token was rejected
            by Google; the user must sign in again.
    """
    await auth_service.get_valid_access_token(user, force=True)
    return TokenRefreshResponse()


@router.post("/logout", response_model=LogoutResponse, summary="Sign out")
async def logout(
    request: Request,
    response: Response,
    user: CurrentUserDep,
    auth_service: GoogleAuthServiceDep,
    settings: SettingsDep,
) -> LogoutResponse:
    """Revoke the current session and best-effort revoke the Google grant."""
    raw_session_token = request.cookies.get(settings.session.cookie_name)
    if raw_session_token is not None:
        await auth_service.logout(raw_session_token=raw_session_token, user=user)
    response.delete_cookie(settings.session.cookie_name, path="/")
    return LogoutResponse()
