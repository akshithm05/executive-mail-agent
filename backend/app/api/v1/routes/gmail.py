"""Gmail endpoints: profile, labels, messages, attachments, search.

Every handler depends on :data:`~app.api.deps.GmailClientDep`, which already
requires an active first-party session (:data:`~app.api.deps.CurrentUserDep`)
and transparently refreshes the user's Google access token before the client
is constructed -- handlers never touch tokens directly.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Query, status

from app.api.deps import GmailClientDep
from app.infra.google import types as gmail_types
from app.schemas.gmail import (
    AttachmentMetaResponse,
    AttachmentResponse,
    CreateLabelRequest,
    GmailProfileResponse,
    LabelListResponse,
    LabelResponse,
    MessageResponse,
    MessagesPageResponse,
    MessageSummaryResponse,
)

router = APIRouter(prefix="/gmail", tags=["gmail"])

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 500


def _to_label_response(label: gmail_types.GmailLabel) -> LabelResponse:
    return LabelResponse(
        id=label.id,
        name=label.name,
        type=label.type,
        message_list_visibility=label.message_list_visibility,
        label_list_visibility=label.label_list_visibility,
    )


def _to_message_response(email: gmail_types.ParsedEmail) -> MessageResponse:
    return MessageResponse(
        id=email.id,
        thread_id=email.thread_id,
        label_ids=email.label_ids,
        snippet=email.snippet,
        subject=email.subject,
        from_address=email.from_address,
        to_address=email.to_address,
        cc_address=email.cc_address,
        date=email.date,
        text_plain=email.text_plain,
        text_html=email.text_html,
        attachments=[
            AttachmentMetaResponse(
                attachment_id=a.attachment_id,
                filename=a.filename,
                mime_type=a.mime_type,
                size=a.size,
            )
            for a in email.attachments
        ],
    )


@router.get(
    "/profile", response_model=GmailProfileResponse, summary="Get the mailbox profile"
)
async def get_profile(gmail: GmailClientDep) -> GmailProfileResponse:
    """Return the authenticated mailbox's profile (address, message counts)."""
    profile = await gmail.get_profile()
    return GmailProfileResponse(
        email_address=profile.email_address,
        messages_total=profile.messages_total,
        threads_total=profile.threads_total,
        history_id=profile.history_id,
    )


@router.get("/labels", response_model=LabelListResponse, summary="List labels")
async def list_labels(gmail: GmailClientDep) -> LabelListResponse:
    """List every label (system and user-created) in the mailbox."""
    labels = await gmail.list_labels()
    return LabelListResponse(labels=[_to_label_response(label) for label in labels])


@router.post(
    "/labels",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a label",
)
async def create_label(
    body: CreateLabelRequest, gmail: GmailClientDep
) -> LabelResponse:
    """Create a new user label.

    Raises:
        ConflictError: A label with this name already exists (409).
    """
    label = await gmail.create_label(body.name)
    return _to_label_response(label)


@router.get(
    "/messages", response_model=MessagesPageResponse, summary="Search/list messages"
)
async def search_messages(
    gmail: GmailClientDep,
    q: str | None = Query(
        default=None, description="Gmail search syntax, e.g. 'from:x is:unread'."
    ),
    page_token: str | None = Query(default=None, alias="pageToken"),
    max_results: int = Query(
        default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE, alias="maxResults"
    ),
) -> MessagesPageResponse:
    """Search or list messages, paginated via ``pageToken``/``nextPageToken``."""
    page = await gmail.search_messages(
        query=q, page_token=page_token, max_results=max_results
    )
    return MessagesPageResponse(
        messages=[
            MessageSummaryResponse(id=m.id, thread_id=m.thread_id)
            for m in page.messages
        ],
        next_page_token=page.next_page_token,
        result_size_estimate=page.result_size_estimate,
    )


@router.get(
    "/messages/{message_id}", response_model=MessageResponse, summary="Read an email"
)
async def get_message(message_id: str, gmail: GmailClientDep) -> MessageResponse:
    """Fetch and parse a single message: headers, text/HTML body, attachments.

    Raises:
        NotFoundError: No message with this id exists in the mailbox (404).
    """
    email = await gmail.get_message(message_id)
    return _to_message_response(email)


@router.get(
    "/messages/{message_id}/attachments/{attachment_id}",
    response_model=AttachmentResponse,
    summary="Read an attachment",
)
async def get_attachment(
    message_id: str, attachment_id: str, gmail: GmailClientDep
) -> AttachmentResponse:
    """Download one attachment's bytes, base64-encoded in the JSON response.

    Raises:
        NotFoundError: No such attachment exists on this message (404).
    """
    attachment = await gmail.get_attachment(message_id, attachment_id)
    return AttachmentResponse(
        attachment_id=attachment.attachment_id,
        size=attachment.size,
        mime_type=attachment.mime_type,
        data_base64=base64.b64encode(attachment.data).decode("ascii"),
    )
