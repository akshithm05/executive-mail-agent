"""Integration tests for :class:`EmailSearchService`'s hybrid ranking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.agents.embeddings import HashingEmbeddingProvider
from app.agents.schemas import SearchQueryParseResult
from app.config.settings import SearchSettings
from app.infra.db.session import Database
from app.infra.models.email import Email
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.email_search import EmailSearchService

_EMBEDDER = HashingEmbeddingProvider(dimensions=64)


def _parsed(**overrides: object) -> SearchQueryParseResult:
    defaults: dict[str, object] = {
        "semantic_query": "recruiter emails",
        "category": None,
        "is_read": None,
        "has_deadline": None,
        "days_back": None,
        "keyword": None,
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return SearchQueryParseResult(**defaults)  # type: ignore[arg-type]


async def _seed_user(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        user = await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
        return tenant.id, user.id


async def _add_email(
    database: Database,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    subject: str,
    body_text: str = "",
    is_read: bool = True,
    category: str | None = None,
    priority_score: float | None = None,
    received_at: datetime | None = None,
    from_address: str = "sender@example.com",
    embed: bool = True,
) -> Email:
    async with database.session() as session:
        embedding = _EMBEDDER.embed(f"{subject}\n{body_text}") if embed else None
        return await EmailRepository(session).add(
            Email(
                tenant_id=tenant_id,
                user_id=user_id,
                gmail_message_id=f"msg-{uuid.uuid4().hex[:8]}",
                gmail_thread_id=f"thread-{uuid.uuid4().hex[:8]}",
                subject=subject,
                body_text=body_text,
                from_address=from_address,
                is_read=is_read,
                category=category,
                priority_score=priority_score,
                received_at=received_at or datetime.now(UTC),
                embedding=embedding,
                embedding_model=_EMBEDDER.model_name if embed else None,
            )
        )


@pytest.mark.asyncio
async def test_semantic_ranking_prefers_the_closer_match(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    await _add_email(
        database,
        tenant_id,
        user_id,
        subject="Recruiter reaching out about a new role",
        body_text="We have an exciting opportunity for a senior engineer.",
    )
    await _add_email(
        database, tenant_id, user_id, subject="Your pizza order has shipped"
    )

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(
            user_id,
            parsed=_parsed(semantic_query="recruiter emails"),
            limit=10,
            offset=0,
        )

    assert result.total == 2
    assert result.hits[0].email.subject == "Recruiter reaching out about a new role"
    assert result.hits[0].score > result.hits[1].score


@pytest.mark.asyncio
async def test_is_read_filter_applied_at_sql_level(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    await _add_email(database, tenant_id, user_id, subject="Invoice #1", is_read=False)
    await _add_email(database, tenant_id, user_id, subject="Invoice #2", is_read=True)

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(
            user_id, parsed=_parsed(is_read=False), limit=10, offset=0
        )

    assert result.total == 1
    assert result.hits[0].email.subject == "Invoice #1"


@pytest.mark.asyncio
async def test_keyword_is_a_hard_filter(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    await _add_email(
        database,
        tenant_id,
        user_id,
        subject="Update from Deloitte",
        body_text="Following up on our conversation.",
    )
    await _add_email(database, tenant_id, user_id, subject="Unrelated newsletter")

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(
            user_id,
            parsed=_parsed(semantic_query="Deloitte", keyword="Deloitte"),
            limit=10,
            offset=0,
        )

    assert result.total == 1
    assert result.hits[0].email.subject == "Update from Deloitte"


@pytest.mark.asyncio
async def test_days_back_filter_excludes_older_emails(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    now = datetime.now(UTC)
    await _add_email(
        database, tenant_id, user_id, subject="Recent one", received_at=now
    )
    await _add_email(
        database,
        tenant_id,
        user_id,
        subject="Old one",
        received_at=now - timedelta(days=90),
    )

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(
            user_id, parsed=_parsed(days_back=30), limit=10, offset=0
        )

    assert result.total == 1
    assert result.hits[0].email.subject == "Recent one"


@pytest.mark.asyncio
async def test_emails_without_an_embedding_still_surface(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    await _add_email(
        database, tenant_id, user_id, subject="Not yet embedded", embed=False
    )

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(user_id, parsed=_parsed(), limit=10, offset=0)

    assert result.total == 1
    assert result.hits[0].score >= 0.0


@pytest.mark.asyncio
async def test_pagination_slices_the_ranked_results(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    for i in range(5):
        await _add_email(database, tenant_id, user_id, subject=f"Email {i}")

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        page1 = await service.search(user_id, parsed=_parsed(), limit=2, offset=0)
        page2 = await service.search(user_id, parsed=_parsed(), limit=2, offset=2)

    assert page1.total == 5
    assert page2.total == 5
    assert len(page1.hits) == 2
    assert len(page2.hits) == 2
    page1_ids = {hit.email.id for hit in page1.hits}
    page2_ids = {hit.email.id for hit in page2.hits}
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.asyncio
async def test_priority_score_contributes_to_ranking(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    # Same subject/body so semantic score ties -- priority must break it.
    await _add_email(
        database,
        tenant_id,
        user_id,
        subject="Weekly update",
        priority_score=0.1,
    )
    await _add_email(
        database,
        tenant_id,
        user_id,
        subject="Weekly update",
        priority_score=0.9,
    )

    async with database.session() as session:
        service = EmailSearchService(
            EmailRepository(session), _EMBEDDER, SearchSettings()
        )
        result = await service.search(
            user_id, parsed=_parsed(semantic_query="weekly update"), limit=10, offset=0
        )

    assert result.hits[0].email.priority_score == 0.9
