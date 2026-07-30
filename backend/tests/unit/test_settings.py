"""Tests for application settings."""

import pytest
from app.config.settings import DatabaseSettings, OAuthSettings, Settings
from cryptography.fernet import Fernet


def test_database_async_and_sync_dsn_build_correctly() -> None:
    db = DatabaseSettings(host="h", port=1234, user="u", password="p", name="n")
    assert db.async_dsn == "postgresql+asyncpg://u:p@h:1234/n"
    assert db.sync_dsn == "postgresql+psycopg://u:p@h:1234/n"


def test_oauth_scopes_accept_comma_separated_string() -> None:
    oauth = OAuthSettings(scopes="a,b,c")
    assert oauth.scopes == ["a", "b", "c"]


def test_oauth_is_configured_reflects_credentials() -> None:
    assert OAuthSettings(client_id="x", client_secret="y").is_configured is True
    assert OAuthSettings(client_id="", client_secret="").is_configured is False


def test_cors_origins_accept_comma_separated_string() -> None:
    settings = Settings(cors_origins="http://a.com,http://b.com")
    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_is_production_flag() -> None:
    assert Settings(environment="production").is_production is True
    assert Settings(environment="local").is_production is False


def test_list_settings_load_from_real_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: list-typed settings must accept comma-separated env vars.

    Passing values as constructor kwargs (as the other tests above do) goes
    through pydantic-settings' init source, which never attempts JSON
    decoding. Real deployments (Docker, systemd, etc.) always populate
    ``Settings`` from ``os.environ``, which pydantic-settings' env source
    *does* try to JSON-decode for list-typed fields by default -- silently
    bypassing the comma-separated ``field_validator`` unless the field is
    annotated with ``NoDecode``. Only a test that goes through real
    environment variables exercises that path.
    """
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,http://b.com")
    monkeypatch.setenv("GOOGLE_OAUTH_SCOPES", "openid,email")

    settings = Settings()

    assert settings.cors_origins == ["http://a.com", "http://b.com"]
    assert settings.oauth.scopes == ["openid", "email"]


def test_default_token_encryption_key_is_a_valid_fernet_key() -> None:
    # The dev-only default must actually work, or every environment that
    # forgets to override it (i.e. everyone until they read the docs) fails
    # at first use rather than at settings-load time.
    key = Settings().security.token_encryption_key
    Fernet(key.encode("utf-8"))  # raises ValueError if invalid


def test_blank_encryption_key_env_var_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A container env_file line like `SECURITY_TOKEN_ENCRYPTION_KEY=` (no
    # value) sets the var to "" rather than leaving it unset -- this must not
    # override the working default with an invalid empty key.
    monkeypatch.setenv("SECURITY_TOKEN_ENCRYPTION_KEY", "")
    settings = Settings()
    Fernet(settings.security.token_encryption_key.encode("utf-8"))
