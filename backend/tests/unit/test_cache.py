"""Unit tests for :class:`CacheService`'s fail-open contract."""

from __future__ import annotations

import pytest
from app.infra.cache import CacheService
from redis.exceptions import RedisError

from tests.fake_redis import FakeRedis


class _BrokenRedis:
    """A double whose every method raises, simulating Redis being down."""

    async def get(self, key: str) -> str:
        raise RedisError("connection refused")

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        raise RedisError("connection refused")

    async def delete(self, *keys: str) -> int:
        raise RedisError("connection refused")

    async def ping(self) -> bool:
        raise RedisError("connection refused")


@pytest.mark.asyncio
async def test_set_then_get_round_trips_json_values() -> None:
    cache = CacheService(FakeRedis(), default_ttl_seconds=60)  # type: ignore[arg-type]
    await cache.set("k", {"a": 1, "b": [1, 2, 3]})
    assert await cache.get("k") == {"a": 1, "b": [1, 2, 3]}


@pytest.mark.asyncio
async def test_get_on_a_missing_key_is_none() -> None:
    cache = CacheService(FakeRedis(), default_ttl_seconds=60)  # type: ignore[arg-type]
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_delete_evicts_the_key() -> None:
    cache = CacheService(FakeRedis(), default_ttl_seconds=60)  # type: ignore[arg-type]
    await cache.set("k", "v")
    await cache.delete("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_ping_reflects_reachability() -> None:
    cache = CacheService(FakeRedis(), default_ttl_seconds=60)  # type: ignore[arg-type]
    assert await cache.ping() is True


@pytest.mark.asyncio
async def test_every_method_fails_open_when_redis_is_down() -> None:
    cache = CacheService(_BrokenRedis(), default_ttl_seconds=60)  # type: ignore[arg-type]
    # None of these raise -- a cache outage degrades to "always a miss".
    assert await cache.get("k") is None
    await cache.set("k", "v")  # no exception
    await cache.delete("k")  # no exception
    assert await cache.ping() is False


@pytest.mark.asyncio
async def test_corrupt_cached_value_is_treated_as_a_miss() -> None:
    redis = FakeRedis()
    await redis.set("k", "not valid json{{{")
    cache = CacheService(redis, default_ttl_seconds=60)  # type: ignore[arg-type]
    assert await cache.get("k") is None
