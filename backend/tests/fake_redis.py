"""A minimal in-memory async Redis double for tests.

Implements exactly the subset of the ``redis.asyncio.Redis`` interface this
codebase actually calls (see ``app/infra/cache.py`` and ``app/api/
middleware/rate_limit.py``) -- a real dict with real TTL expiry against wall
clock time, not a mock of our own code, matching how ``tests/fake_google``/
``tests/fake_anthropic`` stand in for third-party services elsewhere in this
suite. Tests run hermetically (no external Redis server required).
"""

from __future__ import annotations

import time


class FakeRedis:
    """An in-memory stand-in for ``redis.asyncio.Redis``."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _expire_if_due(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is None:
            return
        _, expires_at = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._store[key]

    async def get(self, key: str) -> str | None:
        """Return the value for ``key``, or ``None`` if unset/expired."""
        self._expire_if_due(key)
        entry = self._store.get(key)
        return entry[0] if entry is not None else None

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | float | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """Set ``key`` to ``value``, expiring after ``ex`` seconds if given.

        ``nx``/``xx`` mirror ``redis.asyncio.Redis.set``'s real semantics
        (only set if the key is absent / already present, respectively) --
        ``app/infra/leader_lock.py``'s ``SET ... NX`` acquisition depends on
        this actually being enforced, not a no-op flag.
        """
        self._expire_if_due(key)
        exists = key in self._store
        if (nx and exists) or (xx and not exists):
            return False
        expires_at = time.monotonic() + ex if ex is not None else None
        self._store[key] = (str(value), expires_at)
        return True

    async def delete(self, *keys: str) -> int:
        """Remove the given keys. Returns how many actually existed."""
        removed = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                removed += 1
        return removed

    async def incr(self, key: str) -> int:
        """Increment ``key`` (starting from 0) and return the new value."""
        self._expire_if_due(key)
        entry = self._store.get(key)
        current = int(entry[0]) if entry is not None else 0
        current += 1
        expires_at = entry[1] if entry is not None else None
        self._store[key] = (str(current), expires_at)
        return current

    async def expire(self, key: str, seconds: int) -> bool:
        """Set a TTL on an existing key. Returns False if the key is unset."""
        entry = self._store.get(key)
        if entry is None:
            return False
        self._store[key] = (entry[0], time.monotonic() + seconds)
        return True

    async def ping(self) -> bool:
        """Always succeeds -- this fake is always "reachable"."""
        return True

    async def aclose(self) -> None:
        """No-op: nothing to release for an in-memory store."""
