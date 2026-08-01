"""Redis-backed cache with a fail-open contract.

Redis is optional infrastructure here, not a hard dependency (see
``RedisSettings``'s docstring): every method on :class:`CacheService` catches
connection/timeout errors, logs a warning, and behaves as an unconditional
cache miss rather than raising. A Redis outage should degrade this
application's performance (more cache misses, slower dashboard/analytics
reads), never its availability.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis_asyncio
from redis.exceptions import RedisError

from app.config.logging import get_logger
from app.config.settings import RedisSettings

logger = get_logger(__name__)


def build_redis_client(settings: RedisSettings) -> redis_asyncio.Redis:
    """Build a Redis client from settings.

    Construction alone never touches the network (redis-py connects
    lazily on first command) -- callers don't need this wrapped in a
    try/except.
    """
    return redis_asyncio.from_url(
        settings.url,
        socket_timeout=settings.socket_timeout_seconds,
        socket_connect_timeout=settings.socket_timeout_seconds,
        decode_responses=True,
    )


class CacheService:
    """A JSON-value cache over Redis, with a fail-open contract.

    Args:
        client: An async Redis client (see :func:`build_redis_client`).
        default_ttl_seconds: TTL applied when :meth:`set` isn't given one.
    """

    def __init__(
        self, client: redis_asyncio.Redis, *, default_ttl_seconds: int
    ) -> None:
        self._client = client
        self._default_ttl_seconds = default_ttl_seconds

    async def get(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or ``None`` on a miss or Redis error."""
        try:
            raw = await self._client.get(key)
        except RedisError as exc:
            logger.warning("cache_get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("cache_value_corrupt", key=key)
            return None

    async def set(
        self, key: str, value: Any, *, ttl_seconds: int | None = None
    ) -> None:
        """Cache ``value`` (JSON-serialized) under ``key``. Never raises."""
        try:
            await self._client.set(
                key, json.dumps(value), ex=ttl_seconds or self._default_ttl_seconds
            )
        except (RedisError, TypeError) as exc:
            logger.warning("cache_set_failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        """Evict ``key`` from the cache. Never raises."""
        try:
            await self._client.delete(key)
        except RedisError as exc:
            logger.warning("cache_delete_failed", key=key, error=str(exc))

    async def ping(self) -> bool:
        """Return True if Redis answers a ``PING``. Never raises."""
        try:
            return bool(await self._client.ping())
        except RedisError as exc:
            logger.warning("cache_ping_failed", error=str(exc))
            return False
