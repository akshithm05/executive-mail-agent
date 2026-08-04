"""Unit tests for the Redis-backed scheduler leader lock."""

from __future__ import annotations

import asyncio

import pytest
from app.infra.leader_lock import (
    release_scheduler_leadership,
    try_acquire_scheduler_leadership,
)
from redis.exceptions import RedisError

from tests.fake_redis import FakeRedis


class _BrokenRedis:
    async def set(self, *args: object, **kwargs: object) -> bool:
        raise RedisError("connection refused")


@pytest.mark.asyncio
async def test_first_acquirer_becomes_leader() -> None:
    redis = FakeRedis()
    assert await try_acquire_scheduler_leadership(redis) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_second_acquirer_does_not_become_leader() -> None:
    redis = FakeRedis()
    assert await try_acquire_scheduler_leadership(redis) is True  # type: ignore[arg-type]
    assert await try_acquire_scheduler_leadership(redis) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unreachable_redis_fails_open_to_leadership() -> None:
    # A single-instance deployment (the common case) must never be blocked
    # from running its own scheduler by a Redis outage -- see the module
    # docstring on app/infra/leader_lock.py.
    assert await try_acquire_scheduler_leadership(_BrokenRedis()) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_leadership_renewal_extends_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The background renewal task keeps the lock alive past its original TTL."""
    import app.infra.leader_lock as leader_lock_module

    monkeypatch.setattr(leader_lock_module, "_RENEWAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(leader_lock_module, "_LOCK_TTL_SECONDS", 0.02)
    redis = FakeRedis()
    assert await try_acquire_scheduler_leadership(redis) is True  # type: ignore[arg-type]

    # Without renewal the lock would have expired by now (TTL was 0.02s);
    # the key surviving proves the background task actually re-extended it.
    await asyncio.sleep(0.05)
    assert await redis.get(leader_lock_module._LOCK_KEY) is not None


@pytest.mark.asyncio
async def test_release_deletes_the_lock_this_process_holds() -> None:
    """A graceful shutdown must free the lock for the next instance.

    Regression test: an un-released lock outlives the process by up to
    _LOCK_TTL_SECONDS, during which a restarted replacement instance loses
    the acquisition race and runs with no scheduler at all for its own
    entire lifetime (leadership is only ever decided once, at startup) --
    this is exactly the bug a live restart surfaced.
    """
    import app.infra.leader_lock as leader_lock_module

    redis = FakeRedis()
    assert await try_acquire_scheduler_leadership(redis) is True  # type: ignore[arg-type]
    assert await redis.get(leader_lock_module._LOCK_KEY) is not None

    await release_scheduler_leadership(redis)  # type: ignore[arg-type]

    assert await redis.get(leader_lock_module._LOCK_KEY) is None
    # A fresh instance can now win the race immediately, rather than
    # waiting out the old lock's TTL.
    assert await try_acquire_scheduler_leadership(redis) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_release_is_a_noop_for_a_process_that_never_acquired_leadership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infra.leader_lock as leader_lock_module

    # Force a clean slate regardless of what earlier tests in this module
    # left behind in the module-level globals.
    monkeypatch.setattr(leader_lock_module, "_current_instance_id", None)
    monkeypatch.setattr(leader_lock_module, "_renewal_task", None)

    redis = FakeRedis()
    await redis.set("someone-elses-key", "untouched")

    await release_scheduler_leadership(redis)  # type: ignore[arg-type]

    # Nothing to release -- must not raise, and must not touch Redis at all.
    assert await redis.get("someone-elses-key") == "untouched"


@pytest.mark.asyncio
async def test_release_does_not_delete_a_lock_it_no_longer_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive check: never delete a lock some other instance now holds."""
    import app.infra.leader_lock as leader_lock_module

    redis = FakeRedis()
    await redis.set(leader_lock_module._LOCK_KEY, "a-different-instance-id")
    monkeypatch.setattr(leader_lock_module, "_current_instance_id", "stale-instance-id")
    monkeypatch.setattr(leader_lock_module, "_renewal_task", None)

    await release_scheduler_leadership(redis)  # type: ignore[arg-type]

    assert await redis.get(leader_lock_module._LOCK_KEY) == "a-different-instance-id"


@pytest.mark.asyncio
async def test_release_survives_a_broken_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.infra.leader_lock as leader_lock_module

    monkeypatch.setattr(leader_lock_module, "_current_instance_id", "some-instance-id")
    monkeypatch.setattr(leader_lock_module, "_renewal_task", None)

    class _BrokenGet:
        async def get(self, *args: object, **kwargs: object) -> str:
            raise RedisError("connection refused")

    await release_scheduler_leadership(_BrokenGet())  # type: ignore[arg-type]
