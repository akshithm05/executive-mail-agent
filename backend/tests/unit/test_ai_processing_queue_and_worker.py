"""Tests for the AI-processing job queue and its background worker."""

import asyncio
import uuid

import pytest
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.workers.ai_processing_worker import AIProcessingWorker


def _job(**overrides: object) -> AIProcessingJob:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "email_id": uuid.uuid4(),
        "gmail_message_id": "msg-1",
    }
    defaults.update(overrides)
    return AIProcessingJob(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_queue_is_fifo() -> None:
    queue = AIProcessingQueue()
    first, second = _job(gmail_message_id="a"), _job(gmail_message_id="b")

    await queue.enqueue(first)
    await queue.enqueue(second)

    assert queue.qsize() == 2
    assert (await queue.dequeue()).gmail_message_id == "a"
    assert (await queue.dequeue()).gmail_message_id == "b"
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_worker_processes_enqueued_jobs() -> None:
    queue = AIProcessingQueue()
    processed: list[str] = []

    async def processor(job: AIProcessingJob) -> None:
        processed.append(job.gmail_message_id)

    worker = AIProcessingWorker(queue, processor=processor)
    worker.start()
    try:
        await queue.enqueue(_job(gmail_message_id="job-1"))
        await asyncio.wait_for(queue.join(), timeout=2)
        assert processed == ["job-1"]
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_worker_retries_transient_failures_then_succeeds() -> None:
    queue = AIProcessingQueue()
    attempts = {"count": 0}

    async def flaky_processor(_job: AIProcessingJob) -> None:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("transient")

    worker = AIProcessingWorker(queue, processor=flaky_processor, max_attempts=3)
    worker.start()
    try:
        await queue.enqueue(_job())
        await asyncio.wait_for(queue.join(), timeout=2)
        assert attempts["count"] == 2
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_worker_gives_up_after_max_attempts_and_continues_processing() -> None:
    queue = AIProcessingQueue()
    calls: list[str] = []

    async def always_fails(job: AIProcessingJob) -> None:
        calls.append(job.gmail_message_id)
        raise RuntimeError("permanent")

    async def succeeds(job: AIProcessingJob) -> None:
        calls.append(job.gmail_message_id)

    processor_calls = {"n": 0}

    async def processor(job: AIProcessingJob) -> None:
        processor_calls["n"] += 1
        if job.gmail_message_id == "bad":
            await always_fails(job)
        else:
            await succeeds(job)

    worker = AIProcessingWorker(queue, processor=processor, max_attempts=2)
    worker.start()
    try:
        await queue.enqueue(_job(gmail_message_id="bad"))
        await queue.enqueue(_job(gmail_message_id="good"))
        await asyncio.wait_for(queue.join(), timeout=2)

        # "bad" was retried up to max_attempts and then given up on; "good"
        # was still processed afterward -- one permanently-failing job must
        # not stall the worker loop.
        assert calls.count("bad") == 2
        assert "good" in calls
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_worker_calls_on_failure_after_exhausting_retries() -> None:
    queue = AIProcessingQueue()
    failures: list[tuple[str, str]] = []

    async def always_fails(_job: AIProcessingJob) -> None:
        raise RuntimeError("permanent")

    async def on_failure(job: AIProcessingJob, error: BaseException) -> None:
        failures.append((job.gmail_message_id, str(error)))

    worker = AIProcessingWorker(
        queue, processor=always_fails, max_attempts=2, on_failure=on_failure
    )
    worker.start()
    try:
        await queue.enqueue(_job(gmail_message_id="doomed"))
        await asyncio.wait_for(queue.join(), timeout=2)
        assert failures == [("doomed", "permanent")]
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_worker_survives_a_failing_on_failure_callback() -> None:
    """A broken failure-handler must not crash the worker loop either."""
    queue = AIProcessingQueue()
    calls: list[str] = []

    async def always_fails(job: AIProcessingJob) -> None:
        calls.append(job.gmail_message_id)
        raise RuntimeError("permanent")

    async def broken_on_failure(_job: AIProcessingJob, _error: BaseException) -> None:
        raise RuntimeError("the failure handler is itself broken")

    worker = AIProcessingWorker(
        queue, processor=always_fails, max_attempts=1, on_failure=broken_on_failure
    )
    worker.start()
    try:
        await queue.enqueue(_job(gmail_message_id="first"))
        await queue.enqueue(_job(gmail_message_id="second"))
        await asyncio.wait_for(queue.join(), timeout=2)
        assert calls == ["first", "second"]
    finally:
        await worker.stop()
