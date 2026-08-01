"""Security response headers, applied to every response.

This is a JSON API (no server-rendered HTML, no inline scripts), so the
Content-Security-Policy can be maximally restrictive -- ``default-src
'none'`` -- rather than the looser policy a page-serving app would need.
Defense-in-depth: none of these headers are the primary defense against
their namesake attack (that's parameterized queries for SQL injection,
JSON-only responses + this CSP for XSS), but browsers that honor them
close off exploitation paths an attacker would otherwise get for free.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_RequestResponder = Callable[[Request], Awaitable[Response]]

_CSP = "; ".join(
    [
        "default-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ]
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security headers to every response.

    Args:
        app: The wrapped ASGI application.
        enable_hsts: Whether to send ``Strict-Transport-Security``. Only
            meaningful (and only sent) when the deployment is actually
            served over HTTPS -- sending HSTS over a plain-HTTP local dev
            server would be actively wrong (it tells the browser to *only*
            use HTTPS for this host going forward).
    """

    def __init__(self, app: object, *, enable_hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._enable_hsts = enable_hsts

    async def dispatch(
        self, request: Request, call_next: _RequestResponder
    ) -> Response:
        """Attach security headers to the response of every request."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = _CSP
        # Legacy header, ignored by modern browsers (superseded by CSP) but
        # harmless to send for the handful of older ones that still honor it.
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if self._enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response
