"""In-process AI-processing job queue.

Ingestion enqueues one job per newly-stored email; a background worker
(``app/workers/ai_processing_worker.py``) dequeues and processes them. Like
:mod:`app.infra.events`, this is in-process only (an ``asyncio.Queue``) --
it does not survive a restart and is not shared across replicas. A
production deployment with more than one API instance should replace this
with a durable broker (e.g. SQS, Redis Streams, Postgres-backed job table);
:class:`AIProcessingQueue`'s narrow interface (``enqueue``/``dequeue``) is
built so that swap does not require touching callers.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class AIProcessingJob:
    """One unit of AI work to perform against a newly-ingested email."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID
    gmail_message_id: str
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AIProcessingQueue:
    """A minimal async FIFO queue of :class:`AIProcessingJob`."""

    def __init__(self, *, max_size: int = 0) -> None:
        self._queue: asyncio.Queue[AIProcessingJob] = asyncio.Queue(maxsize=max_size)

    async def enqueue(self, job: AIProcessingJob) -> None:
        """Add a job to the queue, waiting if it is at capacity."""
        await self._queue.put(job)

    async def dequeue(self) -> AIProcessingJob:
        """Remove and return the next job, waiting until one is available."""
        return await self._queue.get()

    def task_done(self) -> None:
        """Mark the most recently dequeued job as processed."""
        self._queue.task_done()

    def qsize(self) -> int:
        """Return the approximate number of jobs currently queued."""
        return self._queue.qsize()

    async def join(self) -> None:
        """Wait until every enqueued job has been dequeued and marked done.

        Primarily useful in tests, to deterministically wait for a
        background worker to finish draining the queue.
        """
        await self._queue.join()
