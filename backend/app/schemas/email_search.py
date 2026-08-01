"""AI-powered email search request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.email import EmailSummaryRead


class EmailSearchHitRead(BaseModel):
    """One ranked search result."""

    email: EmailSummaryRead
    score: float = Field(ge=0.0, description="Blended semantic/keyword/priority score.")


class EmailSearchResponse(BaseModel):
    """A page of AI-powered search results."""

    query: str
    results: list[EmailSearchHitRead]
    total: int = Field(
        description="Size of the (capped) candidate pool this page is drawn from."
    )
    limit: int
    offset: int
