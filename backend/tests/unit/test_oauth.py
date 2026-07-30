"""Tests for the OAuth configuration helper."""

from urllib.parse import parse_qs, urlparse

from app.config.settings import OAuthSettings
from app.core.oauth import OAuthConfig


def _config() -> OAuthConfig:
    return OAuthConfig.from_settings(
        OAuthSettings(
            client_id="cid",
            client_secret="secret",
            redirect_uri="http://localhost/cb",
            scopes=["openid", "email"],
        )
    )


def test_from_settings_maps_fields() -> None:
    cfg = _config()
    assert cfg.client_id == "cid"
    assert cfg.is_configured is True
    assert cfg.scope_string == "openid email"


def test_build_authorization_url_contains_expected_params() -> None:
    cfg = _config()
    url = cfg.build_authorization_url(state="xyz")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["cid"]
    assert params["state"] == ["xyz"]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email"]
    assert params["access_type"] == ["offline"]
