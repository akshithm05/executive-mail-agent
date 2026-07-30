"""Request-scoped context.

A single context variable holds the current request's correlation id so it can
be retrieved anywhere in the async call stack (handlers, services,
repositories) without threading it through every function signature. structlog
also binds it, so it appears automatically in every log line.
"""

from __future__ import annotations

from contextvars import ContextVar

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    """Store the correlation id for the current request context."""
    _request_id_ctx.set(request_id)


def get_request_id() -> str | None:
    """Return the correlation id for the current request, if any."""
    return _request_id_ctx.get()
