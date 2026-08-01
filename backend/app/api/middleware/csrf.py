"""Double-submit-cookie CSRF protection.

The session cookie is ``httponly`` (see ``SessionSettings`` /
``app/api/v1/routes/auth.py``), so it alone can't be echoed back by
JavaScript. Login instead also issues a second, JS-readable cookie (the
CSRF token); the frontend reads it and sends it back as a header on every
mutating request. A cross-site form/script can make the browser attach
cookies automatically, but it cannot read this cookie's value to put it in
a header -- same-origin policy blocks that -- so a mismatched or missing
header proves the request didn't originate from the app's own frontend.

Only state-changing requests (anything but GET/HEAD/OPTIONS) are checked,
and only when the caller already has a session cookie -- an unauthenticated
request has no ambient authority worth protecting yet.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config.logging import get_logger
from app.config.settings import CSRFSettings, Settings

logger = get_logger(__name__)

_RequestResponder = Callable[[Request], Awaitable[Response]]
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Rejects mutating, cookie-authenticated requests missing a valid CSRF token."""

    def __init__(self, app: object, *, session_cookie_name: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._session_cookie_name = session_cookie_name

    async def dispatch(
        self, request: Request, call_next: _RequestResponder
    ) -> Response:
        """Validate the double-submit CSRF token before passing the request through."""
        settings: Settings | None = getattr(request.app.state, "settings", None)
        csrf: CSRFSettings = settings.csrf if settings is not None else CSRFSettings()

        if not csrf.enabled or request.method in _SAFE_METHODS:
            return await call_next(request)

        # No session cookie -> no ambient authority to forge yet (e.g. the
        # OAuth login/callback exchange itself, which is GET-only anyway).
        if self._session_cookie_name not in request.cookies:
            return await call_next(request)

        cookie_token = request.cookies.get(csrf.cookie_name)
        header_token = request.headers.get(csrf.header_name)
        if (
            not cookie_token
            or not header_token
            or not hmac.compare_digest(cookie_token, header_token)
        ):
            logger.warning("csrf_check_failed", path=request.url.path)
            return JSONResponse(
                status_code=403,
                content={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "csrf_check_failed",
                    "detail": "Missing or invalid CSRF token.",
                },
            )
        return await call_next(request)
