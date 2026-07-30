"""Google OAuth configuration helpers.

Phase 1 scope: expose a small, well-typed helper that turns validated
:class:`~app.config.settings.OAuthSettings` into the values a later phase will
need (authorization URL, scope string, readiness flag). The actual OAuth
exchange, token storage, and Gmail integration are implemented in a later
phase and are intentionally absent here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.config.settings import OAuthSettings


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    """Immutable, validated view of the OAuth configuration.

    This is the object the rest of the application depends on, rather than the
    raw settings, so the OAuth surface can evolve independently of the
    environment-variable layout.
    """

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...]
    authorize_url: str
    token_url: str

    @classmethod
    def from_settings(cls, settings: OAuthSettings) -> OAuthConfig:
        """Build an :class:`OAuthConfig` from validated settings."""
        return cls(
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            scopes=tuple(settings.scopes),
            authorize_url=settings.authorize_url,
            token_url=settings.token_url,
        )

    @property
    def is_configured(self) -> bool:
        """True when client credentials are present."""
        return bool(self.client_id and self.client_secret)

    @property
    def scope_string(self) -> str:
        """Return the space-delimited scope string Google expects."""
        return " ".join(self.scopes)

    def build_authorization_url(self, *, state: str) -> str:
        """Construct the Google consent-screen URL.

        Args:
            state: An opaque, unguessable value used for CSRF protection. The
                caller is responsible for generating and persisting it.

        Returns:
            A fully-formed authorization URL.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scope_string,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{self.authorize_url}?{urlencode(params)}"
