"""Gmail REST API client.

Talks to Gmail's ``users.me`` resource for profile, labels, messages, and
attachments. Every call:

* Waits on the shared token-bucket rate limiter before sending, to self-limit
  bursts against Google's per-user quota.
* Goes through :func:`~app.infra.google.http.send_with_retry` for
  retry/backoff on transient (429/5xx/network) failures.
* Raises a typed :class:`~app.core.exceptions.AppError` for any non-2xx
  response Google returns, so route handlers never see raw ``httpx`` errors.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import GmailSettings
from app.core.exceptions import ConflictError, NotFoundError, UpstreamServiceError
from app.infra.google.http import send_with_retry
from app.infra.google.mime_parser import decode_base64url, parse_message
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.google.types import (
    EmailAttachment,
    GmailLabel,
    GmailProfile,
    MessagesPage,
    MessageSummary,
    ParsedEmail,
)


class GmailClient:
    """Async client for the subset of the Gmail API this application uses.

    Args:
        http_client: The shared async HTTP client.
        settings: Gmail client configuration (base URL, timeouts, retries).
        access_token: A *valid, unexpired* OAuth access token. Callers are
            responsible for refreshing before constructing this client --
            see :mod:`app.services.google_auth_service`.
        rate_limiter: Process-wide token bucket shared across all requests.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: GmailSettings,
        access_token: str,
        rate_limiter: TokenBucketRateLimiter,
    ) -> None:
        self._http = http_client
        self._settings = settings
        self._base_url = f"{settings.api_base_url}/users/me"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._rate_limiter = rate_limiter

    async def _get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        await self._rate_limiter.acquire()
        return await send_with_retry(
            self._http,
            "GET",
            f"{self._base_url}{path}",
            headers=self._headers,
            params=params,
            timeout=self._settings.request_timeout_seconds,
            max_attempts=self._settings.max_retries,
        )

    async def _post(self, path: str, *, json_body: dict[str, Any]) -> httpx.Response:
        await self._rate_limiter.acquire()
        return await send_with_retry(
            self._http,
            "POST",
            f"{self._base_url}{path}",
            headers=self._headers,
            json=json_body,
            timeout=self._settings.request_timeout_seconds,
            max_attempts=self._settings.max_retries,
        )

    async def get_profile(self) -> GmailProfile:
        """Return the authenticated mailbox's profile (``users.getProfile``)."""
        response = await self._get("/profile")
        _raise_for_unexpected(response)
        body: dict[str, Any] = response.json()
        return GmailProfile(
            email_address=body["emailAddress"],
            messages_total=int(body.get("messagesTotal", 0)),
            threads_total=int(body.get("threadsTotal", 0)),
            history_id=str(body.get("historyId", "")),
        )

    async def list_labels(self) -> list[GmailLabel]:
        """List all labels in the mailbox (``users.labels.list``)."""
        response = await self._get("/labels")
        _raise_for_unexpected(response)
        body: dict[str, Any] = response.json()
        return [_to_label(item) for item in body.get("labels", [])]

    async def create_label(
        self,
        name: str,
        *,
        message_list_visibility: str = "show",
        label_list_visibility: str = "labelShow",
    ) -> GmailLabel:
        """Create a new user label (``users.labels.create``).

        Raises:
            ConflictError: A label with this name already exists.
        """
        response = await self._post(
            "/labels",
            json_body={
                "name": name,
                "messageListVisibility": message_list_visibility,
                "labelListVisibility": label_list_visibility,
            },
        )
        if response.status_code == httpx.codes.CONFLICT:
            raise ConflictError(f"A label named {name!r} already exists.")
        _raise_for_unexpected(response)
        return _to_label(response.json())

    async def get_message(self, message_id: str) -> ParsedEmail:
        """Fetch and parse a single message (``users.messages.get``).

        Raises:
            NotFoundError: No message with this id exists in the mailbox.
        """
        response = await self._get(f"/messages/{message_id}", params={"format": "full"})
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(f"Message {message_id!r} was not found.")
        _raise_for_unexpected(response)
        return parse_message(response.json())

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> EmailAttachment:
        """Download one attachment's raw bytes (``users.messages.attachments.get``).

        Gmail's attachment endpoint returns only ``size`` and base64url
        ``data`` -- not the filename or MIME type, which live on the parent
        message's part metadata (see :meth:`get_message`). Callers that need
        the filename/content-type should read them from the message first.

        Raises:
            NotFoundError: No such attachment exists on this message.
        """
        response = await self._get(
            f"/messages/{message_id}/attachments/{attachment_id}"
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(f"Attachment {attachment_id!r} was not found.")
        _raise_for_unexpected(response)
        body: dict[str, Any] = response.json()
        raw = decode_base64url(body["data"])
        return EmailAttachment(
            attachment_id=attachment_id,
            filename="",
            mime_type="application/octet-stream",
            size=int(body.get("size", len(raw))),
            data=raw,
        )

    async def search_messages(
        self,
        *,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 25,
    ) -> MessagesPage:
        """Search/list messages (``users.messages.list``) with pagination.

        Args:
            query: Gmail search syntax, e.g. ``"from:boss@corp.com is:unread"``.
            page_token: Opaque token from a previous page's ``next_page_token``.
            max_results: Page size, capped at Gmail's own maximum of 500.
        """
        params: dict[str, Any] = {"maxResults": min(max_results, 500)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        response = await self._get("/messages", params=params)
        _raise_for_unexpected(response)
        body: dict[str, Any] = response.json()
        return MessagesPage(
            messages=[
                MessageSummary(id=m["id"], thread_id=m["threadId"])
                for m in body.get("messages", []) or []
            ],
            next_page_token=body.get("nextPageToken"),
            result_size_estimate=int(body.get("resultSizeEstimate", 0)),
        )


def _to_label(item: dict[str, Any]) -> GmailLabel:
    return GmailLabel(
        id=item["id"],
        name=item["name"],
        type=item.get("type", "user"),
        message_list_visibility=item.get("messageListVisibility"),
        label_list_visibility=item.get("labelListVisibility"),
    )


def _raise_for_unexpected(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise UpstreamServiceError(
            detail={"status_code": response.status_code, "body": _safe_body(response)}
        )


def _safe_body(response: httpx.Response) -> dict[str, Any]:
    try:
        result: dict[str, Any] = response.json()
        return result
    except ValueError:
        return {"raw": response.text[:500]}
