"""Dependency-injection providers.

FastAPI's ``Depends`` mechanism is the composition root for the request scope.
These providers resolve settings, the request-scoped database session,
repositories, and the Google auth/Gmail seam. Handlers and services depend on
the *return types* of these providers, never on concrete construction — which
keeps the code testable and compliant with the dependency-inversion principle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from anthropic import AsyncAnthropic
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.claude_client import StructuredLLMClient
from app.config.settings import Settings, get_settings
from app.core.crypto import TokenCipher
from app.core.exceptions import ServiceUnavailableError, UnauthorizedError
from app.infra.db.session import Database
from app.infra.google.gmail_client import GmailClient
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.user import User
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.draft_reply import DraftReplyService
from app.services.google_auth_service import GoogleAuthService


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running application.

    Settings are stored on ``app.state`` by the application factory, so this
    provider returns exactly the configuration the app was built with. This
    makes the value injectable in tests rather than a process-wide global.
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:  # pragma: no cover - factory always sets this
        return get_settings()
    return settings


def get_database(request: Request) -> Database:
    """Return the :class:`Database` stored on application state.

    Raises:
        ServiceUnavailableError: If the database was not initialized (which
            should only happen if startup failed).
    """
    database: Database | None = getattr(request.app.state, "db", None)
    if database is None:  # pragma: no cover - defensive; startup guarantees this
        raise ServiceUnavailableError("Database is not initialized.")
    return database


async def get_db_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session that commits on success.

    The session's transaction boundary is the request: it commits if the
    handler returns normally and rolls back if it raises.
    """
    async with database.session() as session:
        yield session


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared async HTTP client used for all Google API calls.

    Raises:
        ServiceUnavailableError: If the client was not initialized (which
            should only happen if startup failed).
    """
    client: httpx.AsyncClient | None = getattr(
        request.app.state, "google_http_client", None
    )
    if client is None:  # pragma: no cover - defensive; startup guarantees this
        raise ServiceUnavailableError("The outbound HTTP client is not initialized.")
    return client


def get_gmail_rate_limiter(request: Request) -> TokenBucketRateLimiter:
    """Return the process-wide Gmail API rate limiter."""
    limiter: TokenBucketRateLimiter | None = getattr(
        request.app.state, "gmail_rate_limiter", None
    )
    if limiter is None:  # pragma: no cover - defensive; startup guarantees this
        raise ServiceUnavailableError("The Gmail rate limiter is not initialized.")
    return limiter


def get_tenant_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TenantRepository:
    """Provide a :class:`TenantRepository` bound to the request session."""
    return TenantRepository(session)


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    """Provide a :class:`UserRepository` bound to the request session."""
    return UserRepository(session)


def get_google_credential_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GoogleCredentialRepository:
    """Provide a :class:`GoogleCredentialRepository` bound to the request session."""
    return GoogleCredentialRepository(session)


def get_session_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SessionRepository:
    """Provide a :class:`SessionRepository` bound to the request session."""
    return SessionRepository(session)


def get_draft_reply_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DraftReplyRepository:
    """Provide a :class:`DraftReplyRepository` bound to the request session."""
    return DraftReplyRepository(session)


def get_draft_reply_service(
    repository: Annotated[DraftReplyRepository, Depends(get_draft_reply_repository)],
) -> DraftReplyService:
    """Provide a :class:`DraftReplyService` bound to the request session."""
    return DraftReplyService(repository)


def get_anthropic_http_client(request: Request) -> httpx.AsyncClient | None:
    """Return the test-injected Anthropic transport, or ``None`` in production.

    Unlike :func:`get_http_client` (required, raises if unset), ``None`` is
    the normal production value here -- :class:`AsyncAnthropic` builds its
    own client when none is given. Tests set
    ``app.state.anthropic_http_client`` to an ``ASGITransport``-backed client
    pointed at the fake Anthropic server (see
    ``tests/fake_anthropic/app.py``).
    """
    return getattr(request.app.state, "anthropic_http_client", None)


async def get_anthropic_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
    http_client: Annotated[
        httpx.AsyncClient | None, Depends(get_anthropic_http_client)
    ],
) -> AsyncIterator[AsyncAnthropic]:
    """Yield a request-scoped :class:`AsyncAnthropic`, closed after the request.

    ``max_retries=0``: as in ``app/agents/email_agent.py``,
    :class:`StructuredLLMClient` owns retry/backoff itself so there is one
    observable retry policy rather than the SDK's own layer retrying
    silently underneath. Only closed here when this dependency built the
    client itself (``http_client is None`` in production); a test-injected
    transport is owned and closed by the test.
    """
    client = AsyncAnthropic(
        api_key=settings.ai.anthropic_api_key,
        timeout=settings.ai.request_timeout_seconds,
        max_retries=0,
        http_client=http_client,
    )
    try:
        yield client
    finally:
        if http_client is None:
            await client.close()


def get_structured_llm_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    client: Annotated[AsyncAnthropic, Depends(get_anthropic_client)],
) -> StructuredLLMClient:
    """Provide a :class:`StructuredLLMClient` for one-off, in-request LLM calls.

    Used by the draft-regenerate endpoint (see
    ``app/api/v1/routes/draft_replies.py``) -- the background email-triage
    worker builds its own separately (see ``app/agents/email_agent.py``)
    since it is not request-scoped.
    """
    return StructuredLLMClient(client, settings.ai, PromptLogRepository(session))


def get_token_cipher(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> TokenCipher:
    """Provide the symmetric cipher used to encrypt/decrypt Google tokens at rest."""
    return TokenCipher(settings.security.token_encryption_key)


def get_google_oauth_client(
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> GoogleOAuthClient:
    """Provide a :class:`GoogleOAuthClient` bound to the shared HTTP client."""
    return GoogleOAuthClient(http_client, settings.oauth)


def get_google_auth_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    oauth_client: Annotated[GoogleOAuthClient, Depends(get_google_oauth_client)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    tenant_repo: Annotated[TenantRepository, Depends(get_tenant_repository)],
    credential_repo: Annotated[
        GoogleCredentialRepository, Depends(get_google_credential_repository)
    ],
    session_repo: Annotated[SessionRepository, Depends(get_session_repository)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GoogleAuthService:
    """Provide the fully-wired :class:`GoogleAuthService` for the request."""
    return GoogleAuthService(
        settings=settings,
        oauth_client=oauth_client,
        cipher=cipher,
        user_repo=user_repo,
        tenant_repo=tenant_repo,
        credential_repo=credential_repo,
        session_repo=session_repo,
        db_session=db_session,
    )


async def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    auth_service: Annotated[GoogleAuthService, Depends(get_google_auth_service)],
) -> User:
    """Resolve the logged-in user from the session cookie.

    Raises:
        UnauthorizedError: No session cookie is present, or it does not map
            to an active (non-expired, non-revoked) session.
    """
    raw_token = request.cookies.get(settings.session.cookie_name)
    if raw_token is None:
        raise UnauthorizedError("No active session. Please sign in.")
    user = await auth_service.get_user_for_session_token(raw_token)
    if user is None:
        raise UnauthorizedError("Your session has expired. Please sign in again.")
    return user


async def get_gmail_client(
    user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[GoogleAuthService, Depends(get_google_auth_service)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[TokenBucketRateLimiter, Depends(get_gmail_rate_limiter)],
) -> GmailClient:
    """Provide a :class:`GmailClient` authenticated for the current user.

    Obtains a currently-valid access token (refreshing transparently if it is
    close to expiry) before constructing the client, so route handlers never
    handle token refresh themselves.

    Raises:
        ReauthenticationRequiredError: Propagated from
            :meth:`GoogleAuthService.get_valid_access_token` if the user must
            go through the consent screen again.
    """
    access_token = await auth_service.get_valid_access_token(user)
    return GmailClient(http_client, settings.gmail, access_token, rate_limiter)


# Convenience aliases for concise handler signatures.
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
TenantRepositoryDep = Annotated[TenantRepository, Depends(get_tenant_repository)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
GoogleAuthServiceDep = Annotated[GoogleAuthService, Depends(get_google_auth_service)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
GmailClientDep = Annotated[GmailClient, Depends(get_gmail_client)]
DraftReplyServiceDep = Annotated[DraftReplyService, Depends(get_draft_reply_service)]
StructuredLLMClientDep = Annotated[
    StructuredLLMClient, Depends(get_structured_llm_client)
]
