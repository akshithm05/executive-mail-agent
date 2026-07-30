"""Structured-output Claude client for the email-triage graph.

Wraps :meth:`anthropic.AsyncAnthropic.messages.parse` -- the SDK's
schema-constrained, Pydantic-validated structured-output helper -- with:

* **Retries**: transient failures (rate limits, connection errors, 5xx, and
  a response that fails Pydantic validation) are retried with exponential
  backoff; a genuine bad request is not.
* **Validation**: every response is parsed into the caller's Pydantic
  ``response_model`` before it reaches a graph node -- a node never sees raw,
  unvalidated JSON.
* **Confidence scores**: every ``response_model`` used in this package
  carries its own ``confidence`` field (see ``app/agents/schemas.py``);
  this client does not compute confidence itself, it just guarantees the
  field is present and type-valid.
* **Logging**: every call attempt (success or exhausted failure) is recorded
  as a :class:`~app.infra.models.prompt_log.PromptLog` row -- the same
  observability table Phase 3 built for exactly this purpose.
"""

from __future__ import annotations

import time
import uuid
from typing import TypeVar

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.logging import get_logger
from app.config.settings import AISettings
from app.infra.models.prompt_log import PromptLog
from app.infra.repositories.prompt_log import PromptLogRepository

logger = get_logger(__name__)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)

_RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
    ValidationError,
)


class NoParsedOutputError(Exception):
    """Claude declined or otherwise produced no parseable structured output.

    Not included in ``_RETRYABLE_EXCEPTIONS``: this usually means a refusal
    or a genuinely unparseable response, which an identical retry is
    unlikely to fix -- it bubbles straight to the caller's degrade-and-log
    handling instead (see ``app/agents/graph.py::_call_llm``).
    """


class StructuredLLMClient:
    """Calls Claude for one structured-output turn, with retry and logging."""

    def __init__(
        self,
        client: AsyncAnthropic,
        settings: AISettings,
        prompt_log_repo: PromptLogRepository,
    ) -> None:
        self._client = client
        self._settings = settings
        self._prompt_logs = prompt_log_repo

    async def complete(
        self,
        *,
        system: str,
        user_message: str,
        response_model: type[ResponseModelT],
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        ai_history_id: uuid.UUID | None,
        node_name: str,
    ) -> ResponseModelT:
        """Run one retried, validated, logged structured-output call.

        Raises:
            Exception: the last error, once retries are exhausted. Graph
                nodes are expected to catch this and degrade gracefully
                (default values, zero confidence) rather than fail the whole
                pipeline over one node -- see ``app/agents/graph.py``.
        """
        start = time.monotonic()
        prompt_text = f"{system}\n\n{user_message}"

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
                stop=stop_after_attempt(self._settings.max_retries),
                wait=wait_exponential_jitter(initial=0.5, max=10.0),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.messages.parse(
                        model=self._settings.model,
                        max_tokens=self._settings.max_output_tokens,
                        system=system,
                        messages=[{"role": "user", "content": user_message}],
                        output_format=response_model,
                    )
                    parsed = response.parsed_output
                    if parsed is None:
                        raise NoParsedOutputError(
                            f"no parsed output (stop_reason={response.stop_reason!r})"
                        )
                    await self._log(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        ai_history_id=ai_history_id,
                        node_name=node_name,
                        prompt_text=prompt_text,
                        response_text=parsed.model_dump_json(),
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        latency_ms=int((time.monotonic() - start) * 1000),
                        status="success",
                    )
                    return parsed
        except Exception as exc:
            await self._log(
                tenant_id=tenant_id,
                user_id=user_id,
                ai_history_id=ai_history_id,
                node_name=node_name,
                prompt_text=prompt_text,
                response_text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error_message=str(exc),
            )
            raise

        # pragma: no cover -- AsyncRetrying always returns or raises above.
        raise AssertionError("unreachable")

    async def _log(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        ai_history_id: uuid.UUID | None,
        node_name: str,
        prompt_text: str,
        response_text: str | None,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        status: str,
        error_message: str | None = None,
    ) -> None:
        await self._prompt_logs.add(
            PromptLog(
                tenant_id=tenant_id,
                user_id=user_id,
                ai_history_id=ai_history_id,
                provider="anthropic",
                model=f"{self._settings.model}:{node_name}",
                prompt_text=prompt_text,
                response_text=response_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )
        )
