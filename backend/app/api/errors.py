"""Centralized error handling.

Every exception that escapes a route handler is converted into a consistent
RFC 9457 ``application/problem+json`` response. Expected domain failures
(:class:`AppError`) map to their declared status and code; request-validation
failures map to 422; anything unexpected becomes a 500 with the details logged
but never leaked to the client.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.api.middleware.context import get_request_id
from app.config.logging import get_logger
from app.core.exceptions import AppError
from app.schemas.system import ProblemDetail

logger = get_logger(__name__)

_PROBLEM_MEDIA_TYPE = "application/problem+json"


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    """Serialize a :class:`ProblemDetail` to a problem+json response."""
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=_PROBLEM_MEDIA_TYPE,
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Handle expected :class:`AppError` subclasses."""
    problem = ProblemDetail(
        title=HTTPStatus(exc.status_code).phrase,
        status=exc.status_code,
        code=exc.code,
        detail=exc.message,
        request_id=get_request_id(),
        errors=exc.detail or None,
    )
    logger.info("app_error", code=exc.code, status_code=exc.status_code)
    return _problem_response(problem)


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request-body/query validation failures (422)."""
    problem = ProblemDetail(
        title="Unprocessable Entity",
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="validation_error",
        detail="One or more request parameters were invalid.",
        request_id=get_request_id(),
        errors={"fields": exc.errors()},
    )
    logger.info("validation_error", error_count=len(exc.errors()))
    return _problem_response(problem)


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle framework-raised HTTP exceptions (404 routes, etc.)."""
    status = exc.status_code
    problem = ProblemDetail(
        title=HTTPStatus(status).phrase,
        status=status,
        code=HTTPStatus(status).name.lower(),
        detail=str(exc.detail),
        request_id=get_request_id(),
    )
    return _problem_response(problem)


async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Handle any exception not otherwise caught (500).

    The exception is logged with a stack trace, but only a generic message and
    the correlation id are returned to the client to avoid leaking internals.
    """
    logger.exception("unhandled_exception", error_type=type(exc).__name__)
    problem = ProblemDetail(
        title="Internal Server Error",
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_error",
        detail="An unexpected error occurred.",
        request_id=get_request_id(),
    )
    return _problem_response(problem)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
