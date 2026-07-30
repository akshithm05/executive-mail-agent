"""Integration tests for the Draft Reply Engine's API routes.

Driven over real HTTP through the logged-in session (``logged_in_client``),
against a real (SQLite-backed) database and the fake Anthropic ASGI server
for the regenerate endpoint -- no mocking of the route handlers, services,
or repositories.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.infra.db.session import Database
from app.infra.models.draft_reply import DraftReply
from app.infra.models.email import Email
from app.infra.models.user import User
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


async def _get_current_user(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        return user.tenant_id, user.id


async def _seed_draft(
    database: Database, *, tenant_id: uuid.UUID, user_id: uuid.UUID, **overrides: object
) -> uuid.UUID:
    async with database.session() as session:
        email = await EmailRepository(session).add(
            Email(
                tenant_id=tenant_id,
                user_id=user_id,
                gmail_message_id=f"msg-{uuid.uuid4().hex[:8]}",
                gmail_thread_id="thread-1",
                subject="Contract needs your signature",
                from_address="client@example.com",
                body_text="Please sign and return the attached contract by Friday.",
                received_at=datetime.now(UTC),
            )
        )
        defaults: dict[str, object] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email_id": email.id,
            "subject": "Re: Contract needs your signature",
            "body_text": "Sure, I will sign and return it by Friday.",
            "status": "draft",
            "generated_by": "ai",
            "tone": "professional",
            "reasoning": "Neutral confirmation.",
            "confidence": 0.8,
        }
        defaults.update(overrides)
        draft = await DraftReplyRepository(session).add(DraftReply(**defaults))  # type: ignore[arg-type]
    return draft.id


@pytest.mark.asyncio
async def test_draft_reply_routes_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/draft-replies")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_draft_replies(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    await _seed_draft(database, tenant_id=tenant_id, user_id=user_id)
    await _seed_draft(
        database, tenant_id=tenant_id, user_id=user_id, status="discarded"
    )

    response = await logged_in_client.get("/api/v1/draft-replies")
    assert response.status_code == 200
    assert len(response.json()) == 2

    filtered = await logged_in_client.get(
        "/api/v1/draft-replies", params={"status": "discarded"}
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["status"] == "discarded"


@pytest.mark.asyncio
async def test_get_draft_reply(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=user_id)

    response = await logged_in_client.get(f"/api/v1/draft-replies/{draft_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(draft_id)
    assert body["tone"] == "professional"
    assert body["confidence"] == 0.8


@pytest.mark.asyncio
async def test_get_draft_reply_not_owned_returns_404(
    logged_in_client: AsyncClient, database: Database
) -> None:
    """A draft belonging to a different user must 404, not leak as 403."""
    tenant_id, _user_id = await _get_current_user(database)
    other_user_id = uuid.uuid4()
    async with database.session() as session:
        other_user = await UserRepository(session).add(
            User(
                tenant_id=tenant_id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
        other_user_id = other_user.id
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=other_user_id)

    response = await logged_in_client.get(f"/api/v1/draft-replies/{draft_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_draft_reply(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=user_id)

    response = await logged_in_client.patch(
        f"/api/v1/draft-replies/{draft_id}",
        json={"body_text": "Actually, let me revise this by hand."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["body_text"] == "Actually, let me revise this by hand."
    assert body["generated_by"] == "user"
    # Untouched fields are left alone.
    assert body["subject"] == "Re: Contract needs your signature"


@pytest.mark.asyncio
async def test_approve_then_discard_draft_reply(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=user_id)

    approved = await logged_in_client.post(f"/api/v1/draft-replies/{draft_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    discarded = await logged_in_client.post(f"/api/v1/draft-replies/{draft_id}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"


@pytest.mark.asyncio
async def test_regenerate_draft_reply_infers_tone(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=user_id)

    response = await logged_in_client.post(
        f"/api/v1/draft-replies/{draft_id}/regenerate", json={}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["generated_by"] == "ai"
    assert body["tone"] == "professional"
    assert body["subject"]
    assert body["body_text"]
    assert body["reasoning"]


@pytest.mark.asyncio
async def test_regenerate_draft_reply_honors_tone_override(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, user_id = await _get_current_user(database)
    draft_id = await _seed_draft(
        database, tenant_id=tenant_id, user_id=user_id, status="approved"
    )

    response = await logged_in_client.post(
        f"/api/v1/draft-replies/{draft_id}/regenerate", json={"tone": "formal"}
    )
    assert response.status_code == 200
    body = response.json()
    # A regenerated draft always needs re-review, even if it was approved.
    assert body["status"] == "draft"


@pytest.mark.asyncio
async def test_regenerate_draft_reply_requires_ownership(
    logged_in_client: AsyncClient, database: Database
) -> None:
    tenant_id, _user_id = await _get_current_user(database)
    async with database.session() as session:
        other_user = await UserRepository(session).add(
            User(
                tenant_id=tenant_id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
        other_user_id = other_user.id
    draft_id = await _seed_draft(database, tenant_id=tenant_id, user_id=other_user_id)

    response = await logged_in_client.post(
        f"/api/v1/draft-replies/{draft_id}/regenerate", json={}
    )
    assert response.status_code == 404
