"""Background worker consuming the AI-processing queue.

Actual AI processing (triage, drafting, summarization) is a later phase; the
default job processor here only logs receipt of the job. The retry/backoff,
cancellation, and per-job error isolation are real and are exactly what a
later phase's real processor will run inside -- only ``processor`` changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter

from app.config.logging import get_logger
from app.infra.queue import AIProcessingJob, AIProcessingQueue

logger = get_logger(__name__)

JobProcessor = Callable[[AIProcessingJob], Awaitable[None]]


async def default_processor(job: AIProcessingJob) -> None:
    """Placeholder AI processing step: logs receipt of the job.

    Replaced by the real pipeline (triage/draft/summarize) in a later phase.
    """
    logger.info(
        "ai_processing_job_received",
        email_id=str(job.email_id),
        user_id=str(job.user_id),
    )


class AIProcessingWorker:
    """Consumes :class:`AIProcessingJob` items and runs a processor over each.

    Args:
        queue: The shared job queue to consume from.
        processor: Async callable invoked per job. Defaults to a no-op
            logger; a later phase injects the real AI pipeline here.
        max_attempts: Retry attempts per job before it is dropped and logged
            as permanently failed (no dead-letter queue yet).
    """

    def __init__(
        self,
        queue: AIProcessingQueue,
        *,
        processor: JobProcessor | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._queue = queue
        self._processor = processor or default_processor
        self._max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the worker's background consume loop, if not already running."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ai-processing-worker")

    async def stop(self) -> None:
        """Cancel the worker loop and wait for it to exit cleanly."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            job = await self._queue.dequeue()
            try:
                await self._process_with_retry(job)
            except Exception:
                logger.exception(
                    "ai_processing_job_failed_permanently",
                    email_id=str(job.email_id),
                    attempts=self._max_attempts,
                )
            finally:
                self._queue.task_done()

    async def _process_with_retry(self, job: AIProcessingJob) -> None:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=0.5, max=10.0),
            reraise=True,
        ):
            with attempt:
                await self._processor(job)
