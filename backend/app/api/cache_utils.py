"""Shared cache-or-compute helper for read-heavy API routes.

Applied to the dashboard summary and analytics endpoints -- expensive
aggregation queries that are safe to serve slightly stale (a short TTL, see
``RedisSettings.default_ttl_seconds``) rather than recomputed on every
request. Not a general-purpose caching layer for the whole API: most routes
here are cheap, per-row reads that don't need it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import TypeAdapter, ValidationError

from app.api.deps import CacheServiceDep
from app.config.logging import get_logger
from app.infra.metrics import CACHE_REQUESTS_TOTAL

logger = get_logger(__name__)

ResultT = TypeVar("ResultT")


def cache_key(*parts: str | uuid.UUID | int) -> str:
    """Build a colon-separated cache key from its parts."""
    return ":".join(str(p) for p in parts)


async def cached(
    cache: CacheServiceDep,
    key: str,
    *,
    adapter: TypeAdapter[ResultT],
    ttl_seconds: int,
    compute: Callable[[], Awaitable[ResultT]],
) -> ResultT:
    """Return the cached value for ``key``, computing and caching it on a miss.

    A cached value that no longer matches ``adapter`` (e.g. the response
    shape changed since it was cached) is treated as a miss rather than a
    hard error -- caching is an optimization, never a correctness dependency.
    """
    raw = await cache.get(key)
    if raw is not None:
        try:
            result = adapter.validate_python(raw)
        except ValidationError:
            logger.warning("cache_value_shape_mismatch", key=key)
        else:
            CACHE_REQUESTS_TOTAL.labels(outcome="hit").inc()
            return result

    CACHE_REQUESTS_TOTAL.labels(outcome="miss").inc()
    value = await compute()
    await cache.set(
        key, adapter.dump_python(value, mode="json"), ttl_seconds=ttl_seconds
    )
    return value
