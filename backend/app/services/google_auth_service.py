"""Google login/logout orchestration.

Coordinates the OAuth HTTP client, credential/session repositories, and token
encryption to implement the full login lifecycle: authorization-URL
construction, callback handling (code exchange + user/tenant provisioning),
first-party session issuance, access-token refresh with reauthentication
detection, and logout (local session revocation + best-effort Google token
revocation). Route handlers depend only on this service, never on the
repositories or the OAuth/Gmail clients directly.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.core.exceptions import ReauthenticationRequiredError
from app.core.oauth import OAuthConfig
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.google.types import GoogleTokenResponse
from app.infra.models.google_credential import GoogleCredential
from app.infra.models.session import Session
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository

logger = get_logger(__name__)

# Refresh proactively once fewer than this many seconds remain, so a request
# in flight never races Google's own expiry.
_REFRESH_SKEW_SECONDS = 120
_SESSION_TOKEN_BYTES = 32
_STATE_TOKEN_BYTES = 32


def _hash_token(raw_token: str) -> str:
    """Hash a raw session/state token for storage or comparison.

    SHA-256 (not a slow password hash) is appropriate here: the input is a
    high-entropy random token, not a low-entropy user-chosen secret, so
    brute-forcing the hash is infeasible regardless of hash speed.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _as_aware_utc(value: datetime) -> datetime:
    """Normalize a possibly-naive datetime to UTC-aware.

    SQLite (used in tests) has no native timezone-aware timestamp type, so
    ``aiosqlite`` round-trips ``DateTime(timezone=True)`` columns as naive
    datetimes, while PostgreSQL (``asyncpg``, production) returns them
    aware. Comparing a naive and an aware datetime raises ``TypeError``, so
    every value read back from the database is normalized here rather than
    relying on driver behavior -- keeping this service correct on both
    dialects, consistent with the rest of the ORM layer (see
    ``app/infra/db/mixins.py``).
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _slugify_email(email: str) -> str:
    """Derive a URL-safe, unique tenant slug from an email address."""
    local_part = email.split("@", 1)[0].lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in local_part).strip("-")
    return f"{slug or 'user'}-{secrets.token_hex(4)}"


class GoogleAuthService:
    """Domain service for Google login, logout, and credential refresh."""

    def __init__(
        self,
        *,
        settings: Settings,
        oauth_client: GoogleOAuthClient,
        cipher: TokenCipher,
        user_repo: UserRepository,
        tenant_repo: TenantRepository,
        credential_repo: GoogleCredentialRepository,
        session_repo: SessionRepository,
        db_session: AsyncSession,
    ) -> None:
        self._settings = settings
        self._oauth_client = oauth_client
        self._cipher = cipher
        self._users = user_repo
        self._tenants = tenant_repo
        self._credentials = credential_repo
        self._sessions = session_repo
        self._db_session = db_session

    @staticmethod
    def generate_state() -> str:
        """Generate a high-entropy CSRF nonce for the OAuth ``state`` parameter."""
        return secrets.token_urlsafe(_STATE_TOKEN_BYTES)

    def build_authorization_url(self, *, state: str) -> str:
        """Build the Google consent-screen redirect URL for a login attempt."""
        config = OAuthConfig.from_settings(self._settings.oauth)
        return config.build_authorization_url(state=state)

    async def complete_login(self, *, code: str) -> User:
        """Exchange an authorization code and provision/update the local user.

        Creates a personal :class:`Tenant` and :class:`User` on first login;
        on subsequent logins, refreshes the cached profile fields and rotates
        the stored Google credential.

        Raises:
            OAuthCallbackError: The code was rejected by Google (propagated
                from the OAuth client).
            ReauthenticationRequiredError: Google did not grant offline
                access (no refresh token on this or any prior login), so
                there is nothing to store for future Gmail calls.
        """
        tokens = await self._oauth_client.exchange_code(code)
        identity = await self._oauth_client.fetch_userinfo(tokens.access_token)

        user = await self._users.get_by_google_subject(identity.sub)
        if user is None:
            tenant = await self._tenants.add(
                Tenant(
                    name=identity.email,
                    slug=_slugify_email(identity.email),
                    plan="free",
                )
            )
            user = await self._users.add(
                User(
                    tenant_id=tenant.id,
                    google_subject=identity.sub,
                    email=identity.email,
                    display_name=identity.name,
                    picture_url=identity.picture,
                )
            )
        else:
            user.display_name = identity.name
            user.picture_url = identity.picture

        await self._store_credential(user, tokens)
        logger.info("google_login_completed", user_id=str(user.id))
        return user

    async def _store_credential(self, user: User, tokens: GoogleTokenResponse) -> None:
        """Persist (encrypted) the tokens from a fresh exchange or refresh."""
        expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
        existing = await self._credentials.get_by_user_id(user.id)

        refresh_token = tokens.refresh_token
        if refresh_token is None and existing is not None:
            refresh_token = self._cipher.decrypt(existing.refresh_token_encrypted)
        if refresh_token is None:
            raise ReauthenticationRequiredError(
                "Google did not grant offline access. Please sign in again."
            )

        access_token_encrypted = self._cipher.encrypt(tokens.access_token)
        refresh_token_encrypted = self._cipher.encrypt(refresh_token)

        if existing is None:
            await self._credentials.add(
                GoogleCredential(
                    user_id=user.id,
                    access_token_encrypted=access_token_encrypted,
                    refresh_token_encrypted=refresh_token_encrypted,
                    scope=tokens.scope,
                    token_type=tokens.token_type,
                    access_token_expires_at=expires_at,
                    needs_reauth=False,
                )
            )
        else:
            existing.access_token_encrypted = access_token_encrypted
            existing.refresh_token_encrypted = refresh_token_encrypted
            existing.scope = tokens.scope
            existing.token_type = tokens.token_type
            existing.access_token_expires_at = expires_at
            existing.needs_reauth = False

    async def get_valid_access_token(self, user: User, *, force: bool = False) -> str:
        """Return a currently-valid Gmail access token, refreshing if needed.

        Args:
            user: The user whose credential should be used.
            force: When ``True``, always refresh against Google regardless of
                the cached token's remaining lifetime (used by the explicit
                ``POST /auth/refresh`` endpoint). Normal Gmail API calls
                should leave this ``False`` and rely on lazy, expiry-based
                refresh.

        Raises:
            ReauthenticationRequiredError: No credential is on file, it was
                already flagged as needing reauthentication, or Google just
                rejected the refresh token (revoked/expired grant).
        """
        credential = await self._credentials.get_by_user_id(user.id)
        if credential is None or credential.needs_reauth:
            raise ReauthenticationRequiredError()

        expiry_cutoff = datetime.now(UTC) + timedelta(seconds=_REFRESH_SKEW_SECONDS)
        current_expiry = _as_aware_utc(credential.access_token_expires_at)
        if not force and current_expiry > expiry_cutoff:
            return self._cipher.decrypt(credential.access_token_encrypted)

        refresh_token = self._cipher.decrypt(credential.refresh_token_encrypted)
        try:
            tokens = await self._oauth_client.refresh_access_token(refresh_token)
        except ReauthenticationRequiredError:
            # Commit immediately: this method's caller (e.g. a route handler)
            # is about to propagate this exception, and the request-scoped
            # session (app/api/deps.py::get_db_session) rolls back on any
            # exception. Without an explicit commit here, the needs_reauth
            # flag would never persist, and every subsequent call would
            # repeat the same doomed refresh against Google instead of
            # short-circuiting to ReauthenticationRequiredError immediately.
            credential.needs_reauth = True
            await self._db_session.commit()
            raise

        credential.access_token_encrypted = self._cipher.encrypt(tokens.access_token)
        if tokens.refresh_token:
            credential.refresh_token_encrypted = self._cipher.encrypt(
                tokens.refresh_token
            )
        credential.access_token_expires_at = datetime.now(UTC) + timedelta(
            seconds=tokens.expires_in
        )
        credential.needs_reauth = False
        logger.info("google_access_token_refreshed", user_id=str(user.id))
        return tokens.access_token

    async def create_session(self, user: User) -> str:
        """Create a first-party session for ``user``.

        Returns:
            The raw session token to store in the client's cookie. Only its
            hash is persisted.
        """
        raw_token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
        await self._sessions.add(
            Session(
                user_id=user.id,
                token_hash=_hash_token(raw_token),
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self._settings.session.ttl_seconds),
            )
        )
        return raw_token

    async def get_user_for_session_token(self, raw_token: str) -> User | None:
        """Resolve a raw session-cookie value to its user.

        Returns ``None`` if the token is missing, expired, or revoked.
        """
        session_row = await self._sessions.get_active_by_token_hash(
            _hash_token(raw_token)
        )
        if session_row is None:
            return None
        return await self._users.get(session_row.user_id)

    async def logout(self, *, raw_session_token: str, user: User) -> None:
        """Revoke the local session and best-effort revoke the Google grant."""
        session_row = await self._sessions.get_active_by_token_hash(
            _hash_token(raw_session_token)
        )
        if session_row is not None:
            await self._sessions.revoke(session_row)

        credential = await self._credentials.get_by_user_id(user.id)
        if credential is not None:
            refresh_token = self._cipher.decrypt(credential.refresh_token_encrypted)
            await self._oauth_client.revoke(refresh_token)
        logger.info("google_logout_completed", user_id=str(user.id))
