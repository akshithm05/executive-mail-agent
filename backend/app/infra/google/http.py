"""Shared retry/backoff strategy for Google API HTTP clients.

Both the OAuth token endpoint and the Gmail REST API are called through
:func:`send_with_retry`, which:

* Retries connection failures, timeouts, and ``429``/``5xx`` responses with
  exponential backoff and jitter.
* Honors the server's ``Retry-After`` header (seconds or an HTTP-date) instead
  of guessing a backoff when Google tells us exactly how long to wait.
* Converts an exhausted retry budget into a typed :class:`AppError` --
  :class:`RateLimitExceededError` for 429, :class:`UpstreamServiceError` for
  5xx -- so route handlers never see a raw ``httpx`` exception.

Non-retryable client errors (4xx other than 429) are left on the response for
the caller to inspect via ``response.raise_for_status()`` / status-specific
handling, since those indicate a bad request rather than a transient failure.
"""

from __future__ import annotations

import email.utils
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.logging import get_logger
from app.core.exceptions import RateLimitExceededError, UpstreamServiceError

logger = get_logger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class TransientGoogleApiError(Exception):
    """A retryable failure calling a Google API (429 or 5xx response)."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.retry_after_seconds = _parse_retry_after(response)
        super().__init__(f"transient Google API error: {response.status_code}")


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse ``Retry-After`` as either delay-seconds or an HTTP-date."""
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return float(max((parsed - datetime.now(UTC)).total_seconds(), 0.0))


def _wait_for_retry(retry_state: RetryCallState) -> float:
    """Prefer the server's ``Retry-After``; otherwise back off exponentially."""
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    if isinstance(exc, TransientGoogleApiError) and exc.retry_after_seconds is not None:
        return exc.retry_after_seconds
    return wait_exponential_jitter(initial=0.5, max=20.0)(retry_state)


async def send_with_retry(
    http_client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int,
    **kwargs: Any,
) -> httpx.Response:
    """Send an HTTP request, retrying transient failures with backoff.

    Args:
        http_client: The shared async HTTP client.
        method: HTTP method (``"GET"``, ``"POST"``, ...).
        url: Absolute or client-relative URL.
        max_attempts: Maximum number of attempts (including the first).
        **kwargs: Forwarded to :meth:`httpx.AsyncClient.request`.

    Returns:
        The response from the first non-retryable outcome (2xx/3xx/4xx other
        than 429).

    Raises:
        RateLimitExceededError: 429 responses persisted past the retry budget.
        UpstreamServiceError: 5xx responses persisted past the retry budget.
    """
    try:
        retryable = (TransientGoogleApiError, httpx.TransportError)
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(retryable),
            stop=stop_after_attempt(max_attempts),
            wait=_wait_for_retry,
            reraise=True,
        ):
            with attempt:
                response = await http_client.request(method, url, **kwargs)
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    logger.warning(
                        "google_api_retryable_status",
                        status_code=response.status_code,
                        url=str(response.request.url),
                    )
                    raise TransientGoogleApiError(response)
                return response
    except TransientGoogleApiError as exc:
        if exc.response.status_code == 429:
            raise RateLimitExceededError() from exc
        raise UpstreamServiceError(
            detail={"status_code": exc.response.status_code, "url": url}
        ) from exc

    # pragma: no cover -- AsyncRetrying always returns or raises above.
    raise AssertionError("unreachable")
