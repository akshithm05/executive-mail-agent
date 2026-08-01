"""Application settings.

All runtime configuration is loaded from environment variables (optionally
sourced from a local ``.env`` file during development) and validated eagerly
with Pydantic. Nothing in the codebase should read ``os.environ`` directly;
everything flows through :class:`Settings` so configuration is typed,
documented, and testable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    Field,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]

# The known-public Fernet key shipped as ``SecuritySettings.token_encryption_key``'s
# default, so local/test environments boot without extra setup. Named at
# module scope (rather than inlined twice) so the production-safety check on
# ``Settings`` (below) and the default it's checking against can never drift
# apart.
_PUBLIC_DEFAULT_FERNET_KEY = "uXpM2wUqBkMfjUlojjT8YEf_tEiiKRknmmhWebNIWrY="


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "aeea"
    password: str = "aeea"  # noqa: S105 - local dev default, overridden in prod
    name: str = "aeea"
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True
    echo: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_dsn(self) -> str:
        """Return the SQLAlchemy async DSN (asyncpg driver)."""
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            path=self.name,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_dsn(self) -> str:
        """Return the SQLAlchemy sync DSN (psycopg driver), used by Alembic."""
        dsn = PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            path=self.name,
        )
        return str(dsn)


class OAuthSettings(BaseSettings):
    """Google OAuth 2.0 configuration.

    Phase 1 only *configured* OAuth; Phase 2 implements the actual
    authorization-code exchange, token refresh, and revocation flows against
    these endpoints.
    """

    model_config = SettingsConfigDict(env_prefix="GOOGLE_OAUTH_", extra="ignore")

    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    scopes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/calendar.events",
        ]
    )
    authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105 - URL, not a secret
    userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    revoke_url: str = "https://oauth2.googleapis.com/revoke"

    @field_validator("scopes", mode="before")
    @classmethod
    def _split_scopes(cls, value: object) -> object:
        """Allow scopes to be provided as a comma/space separated string."""
        if isinstance(value, str):
            separators = "," if "," in value else " "
            return [s.strip() for s in value.split(separators) if s.strip()]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when both client credentials are present."""
        return bool(self.client_id and self.client_secret)


class GmailSettings(BaseSettings):
    """Gmail REST API client configuration."""

    model_config = SettingsConfigDict(env_prefix="GMAIL_", extra="ignore")

    api_base_url: str = "https://gmail.googleapis.com/gmail/v1"
    request_timeout_seconds: float = 15.0
    max_retries: int = 5
    # Google's Gmail API quota is enforced in "quota units"; 1 request unit
    # is the conservative default (most read/list calls cost 1-5 units). This
    # is a client-side self-limit to smooth bursts, not a substitute for
    # honoring the server's 429 + Retry-After.
    requests_per_second: float = 5.0
    burst_capacity: int = 10


class CalendarSettings(BaseSettings):
    """Google Calendar REST API client configuration."""

    model_config = SettingsConfigDict(env_prefix="CALENDAR_", extra="ignore")

    api_base_url: str = "https://www.googleapis.com/calendar/v3"
    request_timeout_seconds: float = 15.0
    max_retries: int = 5
    requests_per_second: float = 5.0
    burst_capacity: int = 10


class AISettings(BaseSettings):
    """Anthropic Claude configuration for the email-triage agent."""

    model_config = SettingsConfigDict(env_prefix="AI_", extra="ignore")

    anthropic_api_key: str = ""
    model: str = "claude-opus-5"
    max_output_tokens: int = 4096
    max_retries: int = 3
    request_timeout_seconds: float = 60.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when an Anthropic API key is present."""
        return bool(self.anthropic_api_key)


class MemorySettings(BaseSettings):
    """Long-term memory subsystem configuration.

    ``embedding_provider`` is the seam for future compatibility with a real
    vector database: today only ``"hashing"`` (the local, dependency-free
    provider in ``app/agents/embeddings.py``) exists, but a value like
    ``"voyage"`` can be added later and switched to here without touching
    any calling code.
    """

    model_config = SettingsConfigDict(env_prefix="MEMORY_", extra="ignore")

    embedding_provider: Literal["hashing"] = "hashing"
    embedding_dimensions: int = 256
    decay_half_life_days: float = 30.0
    retrieval_top_k: int = 6
    summarization_threshold: int = 20


class SecuritySettings(BaseSettings):
    """Secrets and cryptographic configuration."""

    model_config = SettingsConfigDict(env_prefix="SECURITY_", extra="ignore")

    # Fernet key (32 url-safe base64-encoded bytes). This default is fixed and
    # PUBLIC — it exists only so local/test environments boot without extra
    # setup. Production MUST override it via SECURITY_TOKEN_ENCRYPTION_KEY,
    # generated with ``python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())"``.
    token_encryption_key: str = _PUBLIC_DEFAULT_FERNET_KEY

    @field_validator("token_encryption_key", mode="before")
    @classmethod
    def _fall_back_to_default_when_blank(cls, value: object) -> object:
        """Treat an empty env var as unset rather than an invalid Fernet key.

        A container env_file line like ``SECURITY_TOKEN_ENCRYPTION_KEY=``
        (no value) sets the variable to ``""``, which pydantic-settings
        treats as an explicit override -- NOT the same as the variable being
        absent, so the class default would never apply. Without this guard,
        that common footgun turns into an opaque ``Fernet`` ``ValueError`` at
        first use deep in request handling instead of a clear outcome.
        """
        if isinstance(value, str) and not value.strip():
            return cls.model_fields["token_encryption_key"].default
        return value


class SessionSettings(BaseSettings):
    """First-party session-cookie configuration.

    A Google login issues our own server-side session (a random opaque token,
    stored hashed in the ``sessions`` table) rather than a stateless JWT, so
    logout and forced reauthentication can actually revoke it.
    """

    model_config = SettingsConfigDict(env_prefix="SESSION_", extra="ignore")

    cookie_name: str = "aeea_session"
    ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    post_login_redirect_url: str = ""


class RedisSettings(BaseSettings):
    """Redis connection configuration -- caching and distributed rate limiting.

    Redis is optional infrastructure, not a hard dependency: every consumer
    (``app/infra/cache.py``, the rate-limit middleware) is written to fail
    open (log a warning, behave as if uncached/unlimited) if Redis is
    unreachable, so a Redis outage degrades performance, not availability.
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    socket_timeout_seconds: float = 2.0
    default_ttl_seconds: int = 60

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        """Return the ``redis://`` connection URL for this configuration."""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class RateLimitSettings(BaseSettings):
    """Inbound API rate-limit configuration.

    A fixed-window counter per identity (the signed-in user's id, or the
    client IP for unauthenticated requests) -- see
    ``app/api/middleware/rate_limit.py``. Backed by Redis so limits are
    shared across every process/replica; falls back to a single-process
    in-memory counter (still useful, just not shared) if Redis is down.
    """

    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", extra="ignore")

    enabled: bool = True
    requests_per_window: int = 120
    window_seconds: int = 60
    # A separate, more generous budget for unauthenticated requests would
    # invite abuse from a single IP; anonymous traffic gets the same budget
    # as an authenticated user today, kept as one number rather than two so
    # there's one setting to reason about.


class CSRFSettings(BaseSettings):
    """Double-submit-cookie CSRF protection configuration.

    The session cookie is ``httponly`` (see ``SessionSettings`` /
    ``app/api/v1/routes/auth.py``), so a CSRF token needs its own,
    JS-readable cookie: the frontend reads it and echoes it back in a
    header on every mutating request, and the middleware rejects the
    request if the two don't match (see ``app/api/middleware/csrf.py``).
    """

    model_config = SettingsConfigDict(env_prefix="CSRF_", extra="ignore")

    enabled: bool = True
    cookie_name: str = "aeea_csrf_token"
    header_name: str = "X-CSRF-Token"
    token_ttl_seconds: int = 60 * 60 * 24 * 14  # matches the session TTL


class SentrySettings(BaseSettings):
    """Sentry error-tracking configuration."""

    model_config = SettingsConfigDict(env_prefix="SENTRY_", extra="ignore")

    dsn: str = ""
    traces_sample_rate: float = 0.0
    profiles_sample_rate: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when a DSN is present."""
        return bool(self.dsn)


class OTelSettings(BaseSettings):
    """OpenTelemetry distributed-tracing configuration.

    Off by default (no-op instrumentation) -- set ``OTEL_EXPORTER_OTLP_ENDPOINT``
    to point at a collector (e.g. the ``otel-collector``/Grafana Tempo/
    Jaeger service in ``infra/docker-compose.yml``) to enable it.
    """

    model_config = SettingsConfigDict(env_prefix="OTEL_", extra="ignore")

    service_name: str = "aeea-backend"
    exporter_otlp_endpoint: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when an OTLP collector endpoint is present."""
        return bool(self.exporter_otlp_endpoint)


class TelegramSettings(BaseSettings):
    """Telegram Bot API configuration for the Telegram notification channel.

    One bot, owned by this application, sends to any user who has started a
    chat with it and given us their numeric ``chat_id`` (stored per-user in
    :class:`~app.infra.models.notification_channel_config.NotificationChannelConfig`).
    """

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", extra="ignore")

    bot_token: str = ""
    api_base_url: str = "https://api.telegram.org"
    request_timeout_seconds: float = 10.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when a bot token is present."""
        return bool(self.bot_token)


class WhatsAppSettings(BaseSettings):
    """Twilio WhatsApp API configuration.

    Twilio's WhatsApp Business API is plain REST over Basic Auth, so this
    needs no SDK -- ``httpx`` (already a dependency) is sufficient. The
    Twilio account is owned by this application; each user supplies only
    their own destination WhatsApp number.
    """

    model_config = SettingsConfigDict(env_prefix="WHATSAPP_", extra="ignore")

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    # Twilio's WhatsApp sender identity, e.g. "whatsapp:+14155238886".
    from_number: str = ""
    api_base_url: str = "https://api.twilio.com"
    request_timeout_seconds: float = 10.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when Twilio credentials and a sender number are all present."""
        return bool(
            self.twilio_account_sid and self.twilio_auth_token and self.from_number
        )


class SMTPSettings(BaseSettings):
    """Outbound SMTP configuration for the email notification channel.

    Distinct from Gmail (``GmailSettings``), which is used to *read* the
    user's inbox -- this is for the assistant to *send* notification emails
    of its own, to an address the user configures (defaulting to their
    account email).
    """

    model_config = SettingsConfigDict(env_prefix="SMTP_", extra="ignore")

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_address: str = ""
    request_timeout_seconds: float = 10.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_configured(self) -> bool:
        """True when a host and a from-address are present."""
        return bool(self.host and self.from_address)


class PushSettings(BaseSettings):
    """Desktop (Web Push/VAPID) and mobile (FCM) push configuration.

    Desktop push uses the standard Web Push protocol (RFC 8030) signed with
    a VAPID key pair -- generate one with
    ``vapid --applicationServerKey`` (from the ``py-vapid`` package, a
    transitive dependency of ``pywebpush``) or ``openssl ecparam``.

    Mobile push uses Firebase Cloud Messaging's HTTP v1 API, which requires
    a service-account JSON credential (OAuth2, not a static server key --
    the legacy FCM server-key API was retired) and a GCP project id.
    """

    model_config = SettingsConfigDict(env_prefix="PUSH_", extra="ignore")

    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:notifications@example.com"
    # Raw service-account JSON (as a single-line string), not a file path --
    # keeps container deployment to one env var, no volume mount required.
    fcm_service_account_json: str = ""
    fcm_project_id: str = ""
    request_timeout_seconds: float = 10.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_desktop_configured(self) -> bool:
        """True when a VAPID key pair is present (desktop web push)."""
        return bool(self.vapid_private_key and self.vapid_public_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_mobile_configured(self) -> bool:
        """True when FCM credentials are present (mobile push)."""
        return bool(self.fcm_service_account_json and self.fcm_project_id)


class NotificationSettings(BaseSettings):
    """Cross-channel notification-dispatch configuration."""

    model_config = SettingsConfigDict(env_prefix="NOTIFICATION_", extra="ignore")

    # How many times a single failed channel delivery is retried (via the
    # same retry/dead-letter queue scheduled jobs use -- see
    # ``app/services/retry_queue.py``) before it is dead-lettered.
    delivery_max_attempts: int = 5
    # How long a resolved NotificationDelivery audit row is kept before the
    # scheduled cleanup sweep purges it.
    delivery_retention_days: int = 30
    # Fallback timezone for a user's quiet hours when none is configured.
    default_quiet_hours_timezone: str = "UTC"
    webhook_request_timeout_seconds: float = 10.0


class SchedulerSettings(BaseSettings):
    """APScheduler job cadence configuration.

    The scheduler itself always runs (there is no "disabled" mode) -- these
    control how often its background jobs poll, not whether they exist.
    """

    model_config = SettingsConfigDict(env_prefix="SCHEDULER_", extra="ignore")

    reminder_poll_interval_seconds: int = 60
    calendar_sync_interval_seconds: int = 300
    memory_decay_interval_hours: int = 24

    # -- Phase 10: additional scheduled jobs ---------------------------------
    email_poll_interval_seconds: int = 120
    memory_consolidation_interval_hours: int = 24
    retry_queue_interval_seconds: int = 60
    health_check_interval_seconds: int = 120
    cleanup_interval_hours: int = 24

    # Cron-style schedules (UTC). Morning digest fires daily; weekly digest
    # fires once a week on `weekly_digest_weekday` (0=Monday, per Python's
    # `date.weekday()` convention, which APScheduler's cron trigger shares).
    morning_digest_hour_utc: int = 8
    morning_digest_minute_utc: int = 0
    weekly_digest_weekday: int = 0
    weekly_digest_hour_utc: int = 8
    weekly_digest_minute_utc: int = 0

    # -- Cleanup retention windows (days) ------------------------------------
    session_retention_days: int = 30
    prompt_log_retention_days: int = 90
    notification_retention_days: int = 60
    retry_job_retention_days: int = 30

    # -- Health-check thresholds ----------------------------------------------
    # A queue deeper than this on a health-check sweep is reported unhealthy
    # (logged + reflected in the `aeea_health_check_status` metric) -- it
    # doesn't stop anything, since the queues are still self-draining.
    ai_processing_queue_warning_depth: int = 100
    dead_letter_queue_warning_depth: int = 20

    # -- Phase 12: AI-powered search ------------------------------------------
    email_embedding_backfill_interval_seconds: int = 300
    email_embedding_backfill_batch_size: int = 200


class SearchSettings(BaseSettings):
    """AI-powered email search configuration.

    Ranking blends three signals over a bounded, SQL-filtered candidate
    pool (see ``app/services/email_search.py``) -- weights are not user
    configurable today, but live here (not as hardcoded constants) so they
    can be tuned per-deployment without a code change.
    """

    model_config = SettingsConfigDict(env_prefix="SEARCH_", extra="ignore")

    candidate_limit: int = 500
    default_limit: int = 20
    semantic_weight: float = 0.55
    keyword_weight: float = 0.25
    priority_weight: float = 0.20


class AnalyticsSettings(BaseSettings):
    """Analytics dashboard configuration.

    Every analytics query is bounded to a caller-supplied date range (days/
    weeks/months) -- ``max_range_days`` caps how far back a caller can ask
    for, so one request can't force an unbounded table scan.
    """

    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", extra="ignore")

    max_range_days: int = 400
    row_fetch_limit: int = 20_000


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application ---------------------------------------------------------
    app_name: str = "AI Executive Email Assistant"
    environment: Environment = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    git_sha: str = "unknown"

    # -- HTTP / CORS ---------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    request_id_header: str = "X-Request-ID"

    # -- Logging -------------------------------------------------------------
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # -- Nested settings -----------------------------------------------------
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    oauth: OAuthSettings = Field(default_factory=OAuthSettings)
    gmail: GmailSettings = Field(default_factory=GmailSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    ai: AISettings = Field(default_factory=AISettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    whatsapp: WhatsAppSettings = Field(default_factory=WhatsAppSettings)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)
    push: PushSettings = Field(default_factory=PushSettings)
    notification: NotificationSettings = Field(default_factory=NotificationSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    csrf: CSRFSettings = Field(default_factory=CSRFSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    otel: OTelSettings = Field(default_factory=OTelSettings)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Allow CORS origins to be provided as a comma separated string."""
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        """True in the production environment."""
        return self.environment == "production"

    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> Settings:
        """Fail fast at startup rather than silently run production insecurely.

        Every check here is something that is a *reasonable, convenient*
        default for local development and tests but would be a real
        vulnerability in production -- the well-known public Fernet key
        (see ``SecuritySettings``), a non-``Secure`` session cookie, or a
        wildcard/localhost CORS origin. Refusing to boot is deliberately
        loud: a misconfigured production deployment that silently runs
        insecurely is far worse than one that never starts.
        """
        if not self.is_production:
            return self
        errors: list[str] = []
        if self.security.token_encryption_key == _PUBLIC_DEFAULT_FERNET_KEY:
            errors.append(
                "SECURITY_TOKEN_ENCRYPTION_KEY is still the public default -- "
                "generate a real key and set it."
            )
        if not self.session.cookie_secure:
            errors.append("SESSION_COOKIE_SECURE must be true in production.")
        if any(
            origin in ("*", "http://localhost:3000") for origin in self.cors_origins
        ):
            errors.append(
                "CORS_ORIGINS still includes a wildcard or the local dev "
                "frontend origin -- set it to the real production origin(s)."
            )
        if not self.oauth.is_configured:
            errors.append("GOOGLE_OAUTH_CLIENT_ID/SECRET must be set in production.")
        if errors:
            raise ValueError(
                "Refusing to start with insecure production configuration:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    The cache ensures the environment is parsed exactly once per process.
    Tests may clear it via ``get_settings.cache_clear()`` to inject overrides.
    """
    return Settings()
