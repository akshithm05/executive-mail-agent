"""DraftReply CRUD service.

Safety invariant: nothing in this service -- or anywhere else in this
codebase -- calls the Gmail API to send a message or create a Gmail draft.
``approve``/``mark_sent`` only update this table's bookkeeping status; a
real send would be a separate, explicitly human-triggered integration this
codebase does not implement. Drafts are always editable up until that point
(see :meth:`edit`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.infra.models.draft_reply import DraftReply
from app.infra.repositories.draft_reply import DraftReplyRepository
from app.services.crud import CRUDService


class DraftReplyService(CRUDService[DraftReply]):
    """CRUD operations for draft replies, plus status-transition helpers."""

    def __init__(self, repository: DraftReplyRepository) -> None:
        super().__init__(repository)
        self._repo: DraftReplyRepository = repository

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[DraftReply]:
        """Return all draft replies for a given email."""
        return await self._repo.list_by_email(email_id)

    async def list_by_user(
        self, user_id: uuid.UUID, *, status: str | None = None
    ) -> Sequence[DraftReply]:
        """Return a user's draft replies, optionally filtered by status."""
        return await self._repo.list_by_user(user_id, status=status)

    async def edit(
        self,
        draft_id: uuid.UUID,
        *,
        subject: str | None = None,
        body_text: str | None = None,
        body_html: str | None = None,
    ) -> DraftReply | None:
        """Apply a human hand-edit to a draft's wording.

        Only touches the fields actually provided. Marks the draft as
        ``user``-generated once edited -- it no longer reflects solely what
        the AI produced, even if the AI wrote the starting point.
        """
        fields = {
            key: value
            for key, value in (
                ("subject", subject),
                ("body_text", body_text),
                ("body_html", body_html),
            )
            if value is not None
        }
        if not fields:
            return await self.get(draft_id)
        fields["generated_by"] = "user"
        return await self.update(draft_id, **fields)

    async def approve(self, draft_id: uuid.UUID) -> DraftReply | None:
        """Mark a draft as approved, ready to send.

        Does not send anything -- see the module docstring.
        """
        return await self.update(draft_id, status="approved")

    async def discard(self, draft_id: uuid.UUID) -> DraftReply | None:
        """Mark a draft as discarded (rejected, will not be sent)."""
        return await self.update(draft_id, status="discarded")

    async def mark_sent(
        self, draft_id: uuid.UUID, *, gmail_draft_id: str
    ) -> DraftReply | None:
        """Record that a draft was sent through some external send flow.

        This method does not itself send anything -- it only records the
        outcome after the fact, for a caller that performed the actual send
        via its own, separately-authorized integration.
        """
        return await self.update(
            draft_id,
            status="sent",
            gmail_draft_id=gmail_draft_id,
            sent_at=datetime.now(UTC),
        )

    async def replace_generated_content(
        self,
        draft_id: uuid.UUID,
        *,
        subject: str,
        body_text: str,
        tone: str,
        reasoning: str,
        confidence: float,
    ) -> DraftReply | None:
        """Overwrite a draft with newly AI-regenerated content.

        Resets ``status`` back to ``"draft"`` -- a regenerated draft has not
        been reviewed yet, even if the previous version was approved.
        """
        updated = await self.update(
            draft_id,
            subject=subject,
            body_text=body_text,
            tone=tone,
            reasoning=reasoning,
            confidence=confidence,
            status="draft",
            generated_by="ai",
        )
        return updated
