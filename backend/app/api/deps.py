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
import redis.asyncio as redis_asyncio
from anthropic import AsyncAnthropic
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.claude_client import StructuredLLMClient
from app.agents.embeddings import EmbeddingProvider, HashingEmbeddingProvider
from app.config.settings import Settings, get_settings
from app.core.crypto import TokenCipher
from app.core.exceptions import ServiceUnavailableError, UnauthorizedError
from app.infra.cache import CacheService
from app.infra.db.session import Database
from app.infra.google.gmail_client import GmailClient
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.user import User
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)
from app.infra.repositories.notification_quiet_hours import (
    NotificationQuietHoursRepository,
)
from app.infra.repositories.notification_rule import NotificationRuleRepository
from app.infra.repositories.preference import PreferenceRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.push_device import PushDeviceRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.task import TaskRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.analytics import AnalyticsService
from app.services.calendar_event import CalendarEventService
from app.services.dashboard import DashboardService
from app.services.draft_reply import DraftReplyService
from app.services.email import EmailService
from app.services.email_search import EmailSearchService
from app.services.google_auth_service import GoogleAuthService
from app.services.notification import NotificationService
from app.services.notification_channels import NotificationChannelConfigService
from app.services.notification_dispatch import ChannelSenders, build_channel_senders
from app.services.notification_rules import NotificationRuleService
from app.services.preference import PreferenceService
from app.services.push_devices import PushDeviceService
from app.services.quiet_hours import NotificationQuietHoursService
from app.services.retry_queue import RetryQueueService
from app.services.search_query_parser import SearchQueryParser
from app.services.task import TaskService


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


def get_redis_client(request: Request) -> redis_asyncio.Redis:
    """Return the shared async Redis client.

    Raises:
        ServiceUnavailableError: If the client was not initialized (which
            should only happen if startup failed).
    """
    client: redis_asyncio.Redis | None = getattr(request.app.state, "redis", None)
    if client is None:  # pragma: no cover - defensive; startup guarantees this
        raise ServiceUnavailableError("The Redis client is not initialized.")
    return client


def get_cache_service(
    client: Annotated[redis_asyncio.Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CacheService:
    """Provide a :class:`CacheService` bound to the shared Redis client."""
    return CacheService(client, default_ttl_seconds=settings.redis.default_ttl_seconds)


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


def get_email_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmailRepository:
    """Provide an :class:`EmailRepository` bound to the request session."""
    return EmailRepository(session)


def get_email_service(
    repository: Annotated[EmailRepository, Depends(get_email_repository)],
) -> EmailService:
    """Provide an :class:`EmailService` bound to the request session."""
    return EmailService(repository)


def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> EmbeddingProvider:
    """Provide the local, dependency-free embedding provider.

    Shared across search and memory retrieval -- both need to embed into
    the same vector space (see ``app/agents/embeddings.py``), so both
    derive their dimensionality from ``settings.memory.embedding_dimensions``
    rather than each owning a separate setting.
    """
    return HashingEmbeddingProvider(dimensions=settings.memory.embedding_dimensions)


def get_email_search_service(
    email_repo: Annotated[EmailRepository, Depends(get_email_repository)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> EmailSearchService:
    """Provide an :class:`EmailSearchService` bound to the request session."""
    return EmailSearchService(email_repo, embedding_provider, settings.search)


def get_task_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskRepository:
    """Provide a :class:`TaskRepository` bound to the request session."""
    return TaskRepository(session)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> TaskService:
    """Provide a :class:`TaskService` bound to the request session."""
    return TaskService(repository)


def get_notification_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationRepository:
    """Provide a :class:`NotificationRepository` bound to the request session."""
    return NotificationRepository(session)


def get_notification_service(
    repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
) -> NotificationService:
    """Provide a :class:`NotificationService` bound to the request session."""
    return NotificationService(repository)


def get_calendar_event_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CalendarEventRepository:
    """Provide a :class:`CalendarEventRepository` bound to the request session."""
    return CalendarEventRepository(session)


def get_calendar_event_service(
    repository: Annotated[
        CalendarEventRepository, Depends(get_calendar_event_repository)
    ],
) -> CalendarEventService:
    """Provide a :class:`CalendarEventService` bound to the request session."""
    return CalendarEventService(repository)


def get_preference_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PreferenceRepository:
    """Provide a :class:`PreferenceRepository` bound to the request session."""
    return PreferenceRepository(session)


def get_preference_service(
    repository: Annotated[PreferenceRepository, Depends(get_preference_repository)],
) -> PreferenceService:
    """Provide a :class:`PreferenceService` bound to the request session."""
    return PreferenceService(repository)


def get_dashboard_service(
    email_repo: Annotated[EmailRepository, Depends(get_email_repository)],
    task_repo: Annotated[TaskRepository, Depends(get_task_repository)],
    notification_repo: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
    draft_reply_repo: Annotated[
        DraftReplyRepository, Depends(get_draft_reply_repository)
    ],
) -> DashboardService:
    """Provide a :class:`DashboardService` bound to the request session."""
    return DashboardService(email_repo, task_repo, notification_repo, draft_reply_repo)


def get_analytics_service(
    email_repo: Annotated[EmailRepository, Depends(get_email_repository)],
    task_repo: Annotated[TaskRepository, Depends(get_task_repository)],
    draft_reply_repo: Annotated[
        DraftReplyRepository, Depends(get_draft_reply_repository)
    ],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AnalyticsService:
    """Provide an :class:`AnalyticsService` bound to the request session."""
    return AnalyticsService(
        email_repo,
        task_repo,
        draft_reply_repo,
        row_fetch_limit=settings.analytics.row_fetch_limit,
    )


def get_failed_job_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FailedJobRepository:
    """Provide a :class:`FailedJobRepository` bound to the request session."""
    return FailedJobRepository(session)


def get_retry_queue_service(
    repository: Annotated[FailedJobRepository, Depends(get_failed_job_repository)],
) -> RetryQueueService:
    """Provide a :class:`RetryQueueService` bound to the request session."""
    return RetryQueueService(repository)


def get_notification_channel_config_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationChannelConfigRepository:
    """Provide a :class:`NotificationChannelConfigRepository` for the request."""
    return NotificationChannelConfigRepository(session)


def get_notification_channel_config_service(
    repository: Annotated[
        NotificationChannelConfigRepository,
        Depends(get_notification_channel_config_repository),
    ],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> NotificationChannelConfigService:
    """Provide a :class:`NotificationChannelConfigService` for the request."""
    return NotificationChannelConfigService(repository, cipher)


def get_push_device_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PushDeviceRepository:
    """Provide a :class:`PushDeviceRepository` bound to the request session."""
    return PushDeviceRepository(session)


def get_push_device_service(
    repository: Annotated[PushDeviceRepository, Depends(get_push_device_repository)],
    cipher: Annotated[TokenCipher, Depends(get_token_cipher)],
) -> PushDeviceService:
    """Provide a :class:`PushDeviceService` bound to the request session."""
    return PushDeviceService(repository, cipher)


def get_notification_rule_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationRuleRepository:
    """Provide a :class:`NotificationRuleRepository` bound to the request session."""
    return NotificationRuleRepository(session)


def get_notification_rule_service(
    repository: Annotated[
        NotificationRuleRepository, Depends(get_notification_rule_repository)
    ],
) -> NotificationRuleService:
    """Provide a :class:`NotificationRuleService` bound to the request session."""
    return NotificationRuleService(repository)


def get_notification_quiet_hours_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationQuietHoursRepository:
    """Provide a :class:`NotificationQuietHoursRepository` for the request."""
    return NotificationQuietHoursRepository(session)


def get_notification_quiet_hours_service(
    repository: Annotated[
        NotificationQuietHoursRepository,
        Depends(get_notification_quiet_hours_repository),
    ],
) -> NotificationQuietHoursService:
    """Provide a :class:`NotificationQuietHoursService` for the request."""
    return NotificationQuietHoursService(repository)


def get_channel_senders(
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ChannelSenders:
    """Provide one sender per notification channel, sharing the shared HTTP client."""
    return build_channel_senders(http_client, settings)


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


def get_search_query_parser(
    settings: Annotated[Settings, Depends(get_app_settings)],
    llm_client: Annotated[StructuredLLMClient, Depends(get_structured_llm_client)],
) -> SearchQueryParser:
    """Provide a :class:`SearchQueryParser` for the AI-powered search endpoint."""
    return SearchQueryParser(llm_client, settings.ai)


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
EmailServiceDep = Annotated[EmailService, Depends(get_email_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
NotificationServiceDep = Annotated[
    NotificationService, Depends(get_notification_service)
]
CalendarEventServiceDep = Annotated[
    CalendarEventService, Depends(get_calendar_event_service)
]
PreferenceServiceDep = Annotated[PreferenceService, Depends(get_preference_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
RetryQueueServiceDep = Annotated[RetryQueueService, Depends(get_retry_queue_service)]
NotificationChannelConfigServiceDep = Annotated[
    NotificationChannelConfigService, Depends(get_notification_channel_config_service)
]
PushDeviceServiceDep = Annotated[PushDeviceService, Depends(get_push_device_service)]
NotificationRuleServiceDep = Annotated[
    NotificationRuleService, Depends(get_notification_rule_service)
]
NotificationQuietHoursServiceDep = Annotated[
    NotificationQuietHoursService, Depends(get_notification_quiet_hours_service)
]
ChannelSendersDep = Annotated[ChannelSenders, Depends(get_channel_senders)]
RedisClientDep = Annotated[redis_asyncio.Redis, Depends(get_redis_client)]
CacheServiceDep = Annotated[CacheService, Depends(get_cache_service)]
EmailSearchServiceDep = Annotated[EmailSearchService, Depends(get_email_search_service)]
SearchQueryParserDep = Annotated[SearchQueryParser, Depends(get_search_query_parser)]
