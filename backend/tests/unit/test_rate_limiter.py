"""Tests for the client-side Gmail rate limiter."""

import asyncio
import time

import pytest
from app.infra.google.rate_limiter import TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_acquire_within_burst_capacity_does_not_block() -> None:
    limiter = TokenBucketRateLimiter(rate_per_second=1.0, burst_capacity=5)

    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_acquire_beyond_burst_capacity_blocks_until_refilled() -> None:
    limiter = TokenBucketRateLimiter(rate_per_second=10.0, burst_capacity=1)

    await limiter.acquire()  # consumes the only token immediately
    start = time.monotonic()
    await limiter.acquire()  # must wait ~1/10s for the bucket to refill
    elapsed = time.monotonic() - start

    assert elapsed >= 0.08  # allow scheduling jitter below the 0.1s target


@pytest.mark.asyncio
async def test_concurrent_acquires_serialize_without_exceeding_rate() -> None:
    limiter = TokenBucketRateLimiter(rate_per_second=20.0, burst_capacity=1)

    start = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(4)))
    elapsed = time.monotonic() - start

    # 4 acquisitions against a burst of 1 at 20/s should take at least
    # 3 * (1/20) = 0.15s for the remaining 3 tokens to trickle in.
    assert elapsed >= 0.12
