"""Prometheus metrics registry.

One process-wide registry, imported wherever something needs to record a
metric -- scheduled jobs, the AI processing worker, email ingestion. Kept in
its own module (no dependency on FastAPI, the scheduler, or any service) so
nothing needs to import a route or a job to record against it, avoiding
import cycles.

Exposed at ``GET /metrics`` (see ``app/api/v1/routes/system.py``) in
Prometheus text-exposition format -- unauthenticated, per Prometheus scrape
convention (the same convention ``/health/*`` already follows here).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

# -- Scheduled jobs -----------------------------------------------------------
# Every job registered in app/scheduler.py records against these with its own
# `job` label, so a single pair of metrics covers all current and future jobs
# instead of one counter per job.
JOB_RUNS_TOTAL = Counter(
    "aeea_job_runs_total",
    "Number of times a scheduled job has run, by outcome.",
    labelnames=("job", "outcome"),
    registry=REGISTRY,
)
JOB_DURATION_SECONDS = Histogram(
    "aeea_job_duration_seconds",
    "Wall-clock duration of a scheduled job run.",
    labelnames=("job",),
    registry=REGISTRY,
)

# -- Email ingestion / AI pipeline -------------------------------------------
EMAILS_INGESTED_TOTAL = Counter(
    "aeea_emails_ingested_total",
    "Number of emails successfully ingested.",
    registry=REGISTRY,
)
AI_TRIAGE_TOTAL = Counter(
    "aeea_ai_triage_total",
    "Number of email-triage graph runs, by outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)

# -- Queues -------------------------------------------------------------------
AI_PROCESSING_QUEUE_DEPTH = Gauge(
    "aeea_ai_processing_queue_depth",
    "Current depth of the in-process AI processing queue.",
    registry=REGISTRY,
)
RETRY_QUEUE_DEPTH = Gauge(
    "aeea_retry_queue_depth",
    "Number of failed jobs currently pending retry.",
    registry=REGISTRY,
)
DEAD_LETTER_QUEUE_DEPTH = Gauge(
    "aeea_dead_letter_queue_depth",
    "Number of failed jobs that exhausted their retry budget.",
    registry=REGISTRY,
)

# -- Retry queue processing ---------------------------------------------------
RETRY_ATTEMPTS_TOTAL = Counter(
    "aeea_retry_attempts_total",
    "Number of retry attempts processed from the retry queue, by outcome.",
    labelnames=("job_type", "outcome"),
    registry=REGISTRY,
)

# -- Health -------------------------------------------------------------------
HEALTH_CHECK_STATUS = Gauge(
    "aeea_health_check_status",
    "Result of the last scheduled health-check sweep for one check (1=up, 0=down).",
    labelnames=("check",),
    registry=REGISTRY,
)

# -- HTTP layer: requests, cache, rate limiting --------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "aeea_http_requests_total",
    "Number of HTTP requests handled, by method/path template/status.",
    labelnames=("method", "path_template", "status_code"),
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "aeea_http_request_duration_seconds",
    "HTTP request handling duration.",
    labelnames=("method", "path_template"),
    registry=REGISTRY,
)
CACHE_REQUESTS_TOTAL = Counter(
    "aeea_cache_requests_total",
    "Number of cache lookups, by outcome (hit/miss).",
    labelnames=("outcome",),
    registry=REGISTRY,
)
RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "aeea_rate_limit_rejections_total",
    "Number of requests rejected for exceeding the rate limit.",
    registry=REGISTRY,
)


@asynccontextmanager
async def track_job(job_name: str) -> AsyncIterator[None]:
    """Record duration and success/failure outcome for one scheduled job run.

    Does not swallow the exception -- callers (``app/scheduler.py``) still
    wrap each job in its own try/except for logging and to guarantee one
    job's failure never stops the scheduler or other jobs; this only adds
    the metrics observation around that.
    """
    start = time.monotonic()
    try:
        yield
    except Exception:
        JOB_RUNS_TOTAL.labels(job=job_name, outcome="failure").inc()
        raise
    else:
        JOB_RUNS_TOTAL.labels(job=job_name, outcome="success").inc()
    finally:
        JOB_DURATION_SECONDS.labels(job=job_name).observe(time.monotonic() - start)
