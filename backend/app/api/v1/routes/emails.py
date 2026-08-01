"""Email endpoints: inbox listing, urgent/deadline views, read/star toggling.

Every handler is scoped to the current user via :data:`CurrentUserDep` --
list endpoints filter by ``user_id`` in the query itself, and the
single-email endpoints use :func:`_get_owned_email` (mirrors
``app/api/v1/routes/draft_replies.py``'s ``_get_owned_draft``) so a request
for another user's email 404s rather than leaking existence.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentUserDep,
    EmailSearchServiceDep,
    EmailServiceDep,
    SearchQueryParserDep,
)
from app.core.exceptions import NotFoundError
from app.infra.models.email import Email
from app.schemas.email import EmailRead, EmailSummaryRead
from app.schemas.email_search import EmailSearchHitRead, EmailSearchResponse

router = APIRouter(prefix="/emails", tags=["emails"])


async def _get_owned_email(
    email_id: uuid.UUID, user: CurrentUserDep, service: EmailServiceDep
) -> Email:
    """Fetch an email, scoped to the current user (404 if not theirs)."""
    email = await service.get(email_id)
    if email is None or email.user_id != user.id:
        raise NotFoundError("No email with this id was found.")
    return email


OwnedEmailDep = Annotated[Email, Depends(_get_owned_email)]


@router.get("", response_model=list[EmailSummaryRead], summary="List inbox emails")
async def list_emails(
    user: CurrentUserDep,
    service: EmailServiceDep,
    category: str | None = Query(default=None),
    is_read: bool | None = Query(default=None),
    has_deadline: bool | None = Query(default=None),
    sort: Literal["recent", "priority"] = Query(default="recent"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[EmailSummaryRead]:
    """List the current user's emails, filtered/sorted for dashboard views."""
    emails = await service.list_for_dashboard(
        user.id,
        category=category,
        is_read=is_read,
        has_deadline=has_deadline,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [EmailSummaryRead.model_validate(e) for e in emails]


@router.get(
    "/search", response_model=EmailSearchResponse, summary="AI-powered hybrid search"
)
async def search_emails(
    user: CurrentUserDep,
    query_parser: SearchQueryParserDep,
    search_service: EmailSearchServiceDep,
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> EmailSearchResponse:
    """Search the current user's emails with a natural-language query.

    Combines SQL filters (category, read/unread, date range, a literal
    keyword) extracted from ``q`` with semantic/embedding similarity
    ranking -- e.g. "unread invoices" filters to unread while semantically
    ranking by "invoices"; "emails mentioning Deloitte" filters to a literal
    substring match. See ``app/services/search_query_parser.py`` and
    ``app/services/email_search.py`` for the two-stage pipeline.
    """
    parsed = await query_parser.parse(q, tenant_id=user.tenant_id, user_id=user.id)
    result = await search_service.search(
        user.id, parsed=parsed, limit=limit, offset=offset
    )
    return EmailSearchResponse(
        query=q,
        results=[
            EmailSearchHitRead(
                email=EmailSummaryRead.model_validate(hit.email), score=hit.score
            )
            for hit in result.hits
        ],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/urgent", response_model=list[EmailSummaryRead], summary="List urgent emails"
)
async def list_urgent_emails(
    user: CurrentUserDep,
    service: EmailServiceDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[EmailSummaryRead]:
    """List the most urgent emails: action_required or high priority score."""
    emails = await service.list_urgent(user.id, limit=limit)
    return [EmailSummaryRead.model_validate(e) for e in emails]


@router.get(
    "/deadlines",
    response_model=list[EmailSummaryRead],
    summary="List emails with an upcoming deadline",
)
async def list_deadline_emails(
    user: CurrentUserDep,
    service: EmailServiceDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[EmailSummaryRead]:
    """List emails with a future deadline, soonest first."""
    emails = await service.list_upcoming_deadlines(user.id, limit=limit)
    return [EmailSummaryRead.model_validate(e) for e in emails]


@router.get("/{email_id}", response_model=EmailRead, summary="Get one email")
async def get_email(email: OwnedEmailDep) -> EmailRead:
    """Fetch a single email's full content by id."""
    return EmailRead.model_validate(email)


@router.post("/{email_id}/read", response_model=EmailRead, summary="Mark email read")
async def mark_email_read(email: OwnedEmailDep, service: EmailServiceDep) -> EmailRead:
    """Mark an email as read."""
    updated = await service.mark_read(email.id)
    return EmailRead.model_validate(cast(Email, updated))


@router.post("/{email_id}/star", response_model=EmailRead, summary="Toggle email star")
async def toggle_email_star(
    email: OwnedEmailDep, service: EmailServiceDep
) -> EmailRead:
    """Toggle an email's starred flag."""
    updated = await service.update(email.id, is_starred=not email.is_starred)
    return EmailRead.model_validate(cast(Email, updated))
