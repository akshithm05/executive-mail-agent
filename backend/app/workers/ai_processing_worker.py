"""Background worker consuming the AI-processing queue.

The retry/backoff, cancellation, and per-job error isolation are the fault-
tolerance seam every real processor (``app/agents/email_agent.py``'s
``run_email_triage``, wired in ``app/main.py``) runs inside. A job that
exhausts its retries here is not dropped -- it is handed to ``on_failure``
(when configured), which ``app/main.py`` wires to push it onto the generic
retry / dead-letter queue (see ``app/services/retry_queue.py``) so it is
still visible and retryable later instead of being silently lost.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter

from app.config.logging import get_logger
from app.infra.metrics import AI_PROCESSING_QUEUE_DEPTH
from app.infra.queue import AIProcessingJob, AIProcessingQueue

logger = get_logger(__name__)

JobProcessor = Callable[[AIProcessingJob], Awaitable[None]]
FailureHandler = Callable[[AIProcessingJob, BaseException], Awaitable[None]]


async def default_processor(job: AIProcessingJob) -> None:
    """Placeholder AI processing step: logs receipt of the job.

    Only used if the caller doesn't inject the real pipeline.
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
            logger; production injects the real AI pipeline here.
        max_attempts: Retry attempts per job before it is considered
            permanently failed for this run.
        on_failure: Optional callback invoked once a job exhausts its
            retries here -- the hook point for pushing it onto the durable
            retry/dead-letter queue instead of just logging and dropping it.
    """

    def __init__(
        self,
        queue: AIProcessingQueue,
        *,
        processor: JobProcessor | None = None,
        max_attempts: int = 3,
        on_failure: FailureHandler | None = None,
    ) -> None:
        self._queue = queue
        self._processor = processor or default_processor
        self._max_attempts = max_attempts
        self._on_failure = on_failure
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
            AI_PROCESSING_QUEUE_DEPTH.set(self._queue.qsize())
            try:
                await self._process_with_retry(job)
            except Exception as exc:
                logger.exception(
                    "ai_processing_job_failed_permanently",
                    email_id=str(job.email_id),
                    attempts=self._max_attempts,
                )
                if self._on_failure is not None:
                    try:
                        await self._on_failure(job, exc)
                    except Exception:
                        logger.exception(
                            "ai_processing_failure_handler_failed",
                            email_id=str(job.email_id),
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
