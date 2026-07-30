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

from pydantic import Field, PostgresDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]


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
    token_encryption_key: str = "uXpM2wUqBkMfjUlojjT8YEf_tEiiKRknmmhWebNIWrY="  # noqa: S105

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


class SchedulerSettings(BaseSettings):
    """APScheduler job cadence configuration.

    The scheduler itself always runs (there is no "disabled" mode) -- these
    control how often its background jobs poll, not whether they exist.
    """

    model_config = SettingsConfigDict(env_prefix="SCHEDULER_", extra="ignore")

    reminder_poll_interval_seconds: int = 60
    calendar_sync_interval_seconds: int = 300
    memory_decay_interval_hours: int = 24


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    The cache ensures the environment is parsed exactly once per process.
    Tests may clear it via ``get_settings.cache_clear()`` to inject overrides.
    """
    return Settings()
