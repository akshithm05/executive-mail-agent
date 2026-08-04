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

# This process's own instance id, set once leadership is acquired --
# `release_scheduler_leadership` needs it to confirm it's deleting its own
# lock, not one a later instance has since acquired.
_current_instance_id: str | None = None


async def try_acquire_scheduler_leadership(client: redis_asyncio.Redis) -> bool:
    """Return True if this process should run the scheduler.

    On success, also starts a background task that periodically renews the
    lock's TTL for as long as this process is alive. Pair with
    :func:`release_scheduler_leadership` in the shutdown path -- an
    un-released lock outlives this process by up to ``_LOCK_TTL_SECONDS``,
    during which a restarted replacement instance loses the acquisition
    race and runs with no scheduler for its own entire lifetime (leadership
    is only ever decided once, at startup).
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
    global _current_instance_id, _renewal_task
    _current_instance_id = instance_id
    _renewal_task = asyncio.create_task(_renew_forever(client, instance_id))
    return True


async def release_scheduler_leadership(client: redis_asyncio.Redis) -> None:
    """Release the leader lock on graceful shutdown, if this process holds it.

    Stops the renewal task and deletes the lock key -- but only if it still
    holds this process's own instance id, so a shutdown never deletes a
    lock some other instance has legitimately acquired since (there
    shouldn't be one, since this process was the leader, but this mirrors
    ``_renew_forever``'s own defensive check rather than assuming it).
    Best-effort: a failure here just means the lock sits until its TTL
    naturally expires, same as before this function existed.
    """
    global _current_instance_id, _renewal_task
    if _renewal_task is not None:
        _renewal_task.cancel()
        _renewal_task = None

    instance_id, _current_instance_id = _current_instance_id, None
    if instance_id is None:
        return

    try:
        current = await client.get(_LOCK_KEY)
        if current == instance_id:
            await client.delete(_LOCK_KEY)
            logger.info("scheduler_leadership_released", instance_id=instance_id)
    except RedisError as exc:
        logger.warning("scheduler_leader_lock_release_failed", error=str(exc))


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
