"""Direct tests for GoogleAuthService against the fake Google server.

These bypass the HTTP layer to test the service in isolation, in particular
that a failed refresh's ``needs_reauth`` flag actually survives -- a bug
caught during development: the request-scoped session rolls back on any
propagating exception, which would silently discard the flag unless the
service commits it explicitly before raising.
"""

from __future__ import annotations

import pytest
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.core.exceptions import ReauthenticationRequiredError
from app.infra.db.session import Database
from app.infra.google.oauth_client import GoogleOAuthClient
from app.infra.models.user import User
from app.infra.repositories.google_credential import GoogleCredentialRepository
from app.infra.repositories.session import SessionRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.google_auth_service import GoogleAuthService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fake_google.app import VALID_AUTH_CODE, FakeGoogleState


def _build_service(
    settings: Settings, http_client: AsyncClient, session: AsyncSession
) -> GoogleAuthService:
    return GoogleAuthService(
        settings=settings,
        oauth_client=GoogleOAuthClient(http_client, settings.oauth),
        cipher=TokenCipher(settings.security.token_encryption_key),
        user_repo=UserRepository(session),
        tenant_repo=TenantRepository(session),
        credential_repo=GoogleCredentialRepository(session),
        session_repo=SessionRepository(session),
        db_session=session,
    )


@pytest.mark.asyncio
async def test_failed_refresh_persists_needs_reauth_and_short_circuits(
    database: Database,
    settings: Settings,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
) -> None:
    async with database.session() as session:
        user: User = await _build_service(
            settings, fake_google_http_client, session
        ).complete_login(code=VALID_AUTH_CODE)

    # Simulate the user revoking Gmail access from their Google account.
    fake_google_state.revoked_tokens.update(fake_google_state.refresh_tokens.keys())

    async with database.session() as session:
        with pytest.raises(ReauthenticationRequiredError):
            await _build_service(
                settings, fake_google_http_client, session
            ).get_valid_access_token(user, force=True)

    calls_after_first_failure = fake_google_state.token_endpoint_calls

    # A second attempt, in a brand-new session/transaction, must see the
    # persisted `needs_reauth` flag and short-circuit -- never re-hitting
    # Google's token endpoint with a refresh token already known to be dead.
    async with database.session() as session:
        with pytest.raises(ReauthenticationRequiredError):
            await _build_service(
                settings, fake_google_http_client, session
            ).get_valid_access_token(user, force=True)

    assert fake_google_state.token_endpoint_calls == calls_after_first_failure
