"""Inbound API rate-limiting middleware.

A fixed-window counter per identity: the session cookie's raw value for an
authenticated caller (each login/device gets its own budget), or the client
IP for an anonymous one (e.g. hitting ``/auth/google/login`` repeatedly).
Backed by Redis (via ``request.app.state.redis``, read per-request so it
sees whatever the lifespan set up -- see ``app/infra/cache.py``'s module
docstring for why this is read lazily rather than injected at construction
time) so the limit is shared across every process/replica; if Redis is
unreachable, an in-process fallback counter takes over so a Redis outage
degrades this to per-process limiting rather than disabling it entirely.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config.logging import get_logger
from app.config.settings import RateLimitSettings, Settings
from app.infra.metrics import RATE_LIMIT_REJECTIONS_TOTAL

logger = get_logger(__name__)

_RequestResponder = Callable[[Request], Awaitable[Response]]

# Paths that must never be rate-limited: the orchestrator's liveness/
# readiness probes and the Prometheus scrape endpoint fire far more often
# than any human-driven request budget would allow.
_EXEMPT_PATH_PREFIXES = ("/api/v1/health", "/api/v1/metrics")


class _InMemoryWindowCounter:
    """Single-process fallback fixed-window counter, used when Redis is down."""

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def hit(self, identity: str, *, window_seconds: int) -> int:
        now = time.monotonic()
        count, window_start = self._counts[identity]
        if now - window_start >= window_seconds:
            count, window_start = 0, now
        count += 1
        self._counts[identity] = (count, window_start)
        return count


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests beyond a per-identity fixed-window budget with 429."""

    def __init__(self, app: object, *, session_cookie_name: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._session_cookie_name = session_cookie_name
        self._fallback = _InMemoryWindowCounter()

    async def dispatch(
        self, request: Request, call_next: _RequestResponder
    ) -> Response:
        """Check the caller's rate-limit budget before passing the request through."""
        settings: Settings | None = getattr(request.app.state, "settings", None)
        rate_limit: RateLimitSettings = (
            settings.rate_limit if settings is not None else RateLimitSettings()
        )
        if (
            not rate_limit.enabled
            or request.method == "OPTIONS"
            or request.url.path.startswith(_EXEMPT_PATH_PREFIXES)
        ):
            return await call_next(request)

        identity = request.cookies.get(self._session_cookie_name) or _client_ip(request)
        count = await self._hit(
            request, identity, window_seconds=rate_limit.window_seconds
        )

        if count > rate_limit.requests_per_window:
            RATE_LIMIT_REJECTIONS_TOTAL.inc()
            logger.warning("rate_limit_exceeded", identity_hash=hash(identity))
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "Too Many Requests",
                    "status": 429,
                    "code": "rate_limit_exceeded",
                    "detail": "Too many requests. Please try again shortly.",
                },
                headers={"Retry-After": str(rate_limit.window_seconds)},
            )
        return await call_next(request)

    async def _hit(
        self, request: Request, identity: str, *, window_seconds: int
    ) -> int:
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is not None:
            try:
                key = f"ratelimit:{identity}"
                count = await redis_client.incr(key)
                if count == 1:
                    await redis_client.expire(key, window_seconds)
                return int(count)
            except RedisError as exc:
                logger.warning("rate_limit_redis_failed", error=str(exc))
        return self._fallback.hit(identity, window_seconds=window_seconds)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
