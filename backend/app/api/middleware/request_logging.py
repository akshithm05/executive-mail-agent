"""Request correlation and access-logging middleware.

This middleware runs once per request and:

* Reads an inbound correlation id from the configured header, or generates one.
* Binds it to the structlog context and the request-context variable so every
  downstream log line and error response can reference it.
* Emits a structured access log with method, path, status, and latency.
* Echoes the correlation id back to the client on the response.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.middleware.context import set_request_id
from app.config.logging import get_logger

logger = get_logger(__name__)

_RequestResponder = Callable[[Request], Awaitable[Response]]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id to each request and log its lifecycle.

    Args:
        app: The wrapped ASGI application.
        header_name: Name of the request/response correlation-id header.
    """

    def __init__(self, app: object, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._header_name = header_name

    async def dispatch(
        self, request: Request, call_next: _RequestResponder
    ) -> Response:
        """Process a single request, binding context and logging the result."""
        request_id = request.headers.get(self._header_name) or uuid.uuid4().hex
        set_request_id(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception("request_failed", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers[self._header_name] = request_id
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
