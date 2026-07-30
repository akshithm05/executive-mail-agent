"""Gmail endpoint request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Gmail enforces a 225-character limit on label names.
_MAX_LABEL_NAME_LENGTH = 225


class GmailProfileResponse(BaseModel):
    """Response for ``GET /gmail/profile``."""

    email_address: str
    messages_total: int
    threads_total: int
    history_id: str


class LabelResponse(BaseModel):
    """A single Gmail label."""

    id: str
    name: str
    type: str
    message_list_visibility: str | None = None
    label_list_visibility: str | None = None


class LabelListResponse(BaseModel):
    """Response for ``GET /gmail/labels``."""

    labels: list[LabelResponse]


class CreateLabelRequest(BaseModel):
    """Request body for ``POST /gmail/labels``."""

    name: str = Field(min_length=1, max_length=_MAX_LABEL_NAME_LENGTH)


class AttachmentMetaResponse(BaseModel):
    """Attachment metadata embedded in a message response (no bytes)."""

    attachment_id: str
    filename: str
    mime_type: str
    size: int


class MessageResponse(BaseModel):
    """Response for ``GET /gmail/messages/{message_id}``."""

    id: str
    thread_id: str
    label_ids: list[str]
    snippet: str
    subject: str
    from_address: str
    to_address: str
    cc_address: str
    date: str
    text_plain: str | None
    text_html: str | None
    attachments: list[AttachmentMetaResponse]


class AttachmentResponse(BaseModel):
    """Response for ``GET /gmail/messages/{message_id}/attachments/{attachment_id}``."""

    attachment_id: str
    size: int
    mime_type: str
    data_base64: str = Field(
        description="Standard (not url-safe) base64-encoded bytes."
    )


class MessageSummaryResponse(BaseModel):
    """One row of a message search/list result."""

    id: str
    thread_id: str


class MessagesPageResponse(BaseModel):
    """Response for ``GET /gmail/messages`` (search, paginated)."""

    messages: list[MessageSummaryResponse]
    next_page_token: str | None
    result_size_estimate: int
