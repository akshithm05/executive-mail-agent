"""Redis-backed leader election for singleton in-process work (the scheduler).

Only one running instance should have its APScheduler actually firing jobs
-- every replica running its own would duplicate reminders, digests,
retry-queue processing, and every other scheduled job in ``app/scheduler.py``.
This is deliberately simple (a single TTL'd lock, periodically renewed,
never hand off) rather than full distributed leader election with
failover: acquire once at startup, hold for this process's lifetime.

If Redis is unreachable, this fails *open* -- every instance assumes
leadership -- which is the opposite of this codebase's usual fail-open
default (usually "treat it as absent/uncached"), and deliberately so: a
single-instance deployment (the common case) needs no lock at all and must
never be blocked from running its own scheduler by a transient Redis
hiccup, and a multi-replica deployment briefly duplicating job execution
during a Redis outage is a far better failure mode than *no* instance
running the scheduler until Redis recovers.
"""

from __future__ import annotations

import asyncio
import uuid

import redis.asyncio as redis_asyncio
from redis.exceptions import RedisError

from app.config.logging import get_logger

logger = get_logger(__name__)

_LOCK_KEY = "aeea:scheduler:leader"
_LOCK_TTL_SECONDS = 60
_RENEWAL_INTERVAL_SECONDS = 20

# Holds a reference to the background renewal task for this process's
# lifetime -- an un-referenced asyncio task is only weakly held by the
# event loop and can be garbage-collected mid-run.
_renewal_task: asyncio.Task[None] | None = None


async def try_acquire_scheduler_leadership(client: redis_asyncio.Redis) -> bool:
    """Return True if this process should run the scheduler.

    On success, also starts a background task that periodically renews the
    lock's TTL for as long as this process is alive.
    """
    instance_id = uuid.uuid4().hex
    try:
        acquired = await client.set(
            _LOCK_KEY, instance_id, nx=True, ex=_LOCK_TTL_SECONDS
        )
    except RedisError as exc:
        logger.warning("scheduler_leader_lock_unavailable", error=str(exc))
        return True

    if not acquired:
        logger.info("scheduler_leadership_not_acquired")
        return False

    logger.info("scheduler_leadership_acquired", instance_id=instance_id)
    global _renewal_task
    _renewal_task = asyncio.create_task(_renew_forever(client, instance_id))
    return True


async def _renew_forever(client: redis_asyncio.Redis, instance_id: str) -> None:
    while True:
        await asyncio.sleep(_RENEWAL_INTERVAL_SECONDS)
        try:
            # Only renew if we still (recognizably) hold it -- defensive;
            # nothing else should have taken it since this process never
            # releases it voluntarily.
            current = await client.get(_LOCK_KEY)
            if current == instance_id:
                await client.expire(_LOCK_KEY, _LOCK_TTL_SECONDS)
            else:
                logger.warning("scheduler_leader_lock_lost", instance_id=instance_id)
                return
        except RedisError as exc:
            logger.warning("scheduler_leader_lock_renewal_failed", error=str(exc))
