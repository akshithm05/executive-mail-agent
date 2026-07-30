"""Client-side rate limiting for outbound Gmail API calls.

This self-imposed limit smooths request bursts so the process does not trip
Google's own per-user quota (which would otherwise surface as 429s that then
have to be retried). It is a single in-process token bucket, so it is
process-wide, not distributed: running multiple API instances still requires
each to honor Google's 429 + ``Retry-After`` (handled separately in
:mod:`app.infra.google.http`) as the authoritative limit.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    """An async token-bucket limiter.

    Args:
        rate_per_second: Steady-state tokens replenished per second.
        burst_capacity: Maximum tokens that can accumulate (i.e. burst size).
    """

    def __init__(self, rate_per_second: float, burst_capacity: int) -> None:
        self._rate = rate_per_second
        self._capacity = float(burst_capacity)
        self._tokens = float(burst_capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait_seconds = (1 - self._tokens) / self._rate
            await asyncio.sleep(wait_seconds)
