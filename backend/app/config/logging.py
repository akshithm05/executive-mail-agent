"""Structured logging configuration.

We use :mod:`structlog` layered on top of the standard library logging module
so that:

* Every log line is structured (JSON in non-local environments, coloured
  key/value console output locally).
* Contextual fields bound during a request (``request_id``, ``method``,
  ``path`` ...) are automatically merged into every log line emitted while
  handling that request, via context variables.
* Third-party libraries that use the stdlib logger (uvicorn, SQLAlchemy,
  Alembic) are funnelled through the *same* renderer for consistent output.

The configuration follows structlog's recommended "render via the standard
library" pattern: application loggers produce structlog event dicts, and a
single :class:`structlog.stdlib.ProcessorFormatter` renders both structlog and
foreign (stdlib) records.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.types import EventDict

from app.config.settings import LogFormat, LogLevel

# Keys that must never be emitted to logs, even if accidentally bound.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "authorization",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "cookie",
        "set-cookie",
    }
)


def _redact_sensitive(
    _logger: object, _method: str, event_dict: EventDict
) -> EventDict:
    """Redact sensitive keys from a log event before it is rendered."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def _build_renderer(fmt: LogFormat) -> structlog.types.Processor:
    """Return the final renderer for the given output format."""
    if fmt == "json":
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer(colors=True)


def configure_logging(level: LogLevel = "INFO", fmt: LogFormat = "json") -> None:
    """Configure structlog and the stdlib logging bridge.

    Args:
        level: Minimum log level to emit.
        fmt: ``"json"`` for machine-readable output or ``"console"`` for
            human-friendly coloured output during local development.

    This function is idempotent and safe to call multiple times (for example
    from tests); the last call wins.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
    ]

    # Application loggers: run shared processors, then hand the event dict to
    # the ProcessorFormatter attached to the stdlib handler.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # The single formatter that renders both structlog and foreign records.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _build_renderer(fmt),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.getLevelName(level))

    # Let uvicorn's access logs flow through the root handler for consistency.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = True
    logging.getLogger("uvicorn.error").handlers = []
    logging.getLogger("uvicorn.error").propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name, typically ``__name__`` of the caller.

    Returns:
        A configured :class:`structlog.stdlib.BoundLogger`.
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
