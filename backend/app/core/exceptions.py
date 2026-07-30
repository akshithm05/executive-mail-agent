"""Application exception hierarchy.

Every error the application raises deliberately inherits from
:class:`AppError`, which carries the metadata needed to render an RFC 9457
"problem details" HTTP response (see :mod:`app.api.errors`). Framework and
transport concerns are intentionally kept out of this module so the domain
layer can raise these exceptions without importing FastAPI.
"""

from __future__ import annotations

from http import HTTPStatus


class AppError(Exception):
    """Base class for all expected application errors.

    Attributes:
        status_code: HTTP status code to return for this error.
        code: Stable, machine-readable error identifier (e.g. ``not_found``).
        message: Human-readable description safe to expose to clients.
        detail: Optional additional context to include in the response body.
    """

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, object] | None = None,
    ) -> None:
        self.message = message or self.message
        self.detail = detail or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    """A requested resource could not be found."""

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with the current resource state."


class ValidationError(AppError):
    """The request failed a business validation rule."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "The request failed validation."


class UnauthorizedError(AppError):
    """Authentication is required or has failed."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    message = "Authentication is required."


class ForbiddenError(AppError):
    """The caller is authenticated but not permitted to perform the action."""

    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action."


class ServiceUnavailableError(AppError):
    """A required downstream dependency is unavailable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A required service is currently unavailable."


class ReauthenticationRequiredError(AppError):
    """The user's Google credential is no longer usable.

    Raised when Google's token endpoint returns ``invalid_grant`` while
    refreshing an access token -- the refresh token has been revoked,
    expired, or the user changed their Google password. There is no
    recovery except sending the user back through the OAuth consent screen.
    """

    status_code = HTTPStatus.UNAUTHORIZED
    code = "reauthentication_required"
    message = "Your Google account connection has expired. Please sign in again."


class UpstreamServiceError(AppError):
    """An upstream Google API returned an unexpected or unrecoverable error."""

    status_code = HTTPStatus.BAD_GATEWAY
    code = "upstream_error"
    message = "Google returned an unexpected error."


class RateLimitExceededError(AppError):
    """A rate limit (ours or Google's) was exceeded for this request."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"
    message = "Too many requests. Please try again shortly."


class OAuthCallbackError(AppError):
    """The Google OAuth authorization-code exchange failed.

    Raised for a bad/expired ``state``, a rejected or already-consumed
    authorization ``code``, or any other failure completing the login
    handshake. The user should be sent back to ``/auth/google/login`` to
    retry -- this is a failed *login attempt*, not an expired *existing*
    session (see :class:`ReauthenticationRequiredError` for that case).
    """

    status_code = HTTPStatus.BAD_REQUEST
    code = "oauth_callback_failed"
    message = "Google sign-in could not be completed. Please try again."
