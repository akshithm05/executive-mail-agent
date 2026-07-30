"""Parses Gmail's nested MIME ``payload`` structure.

Gmail returns messages (``format=full``) as a recursive ``payload`` tree:
container parts (``multipart/alternative``, ``multipart/mixed``, ...) nest
leaf parts that carry either inline body data (base64url-encoded) or a
reference to an attachment (``attachmentId``) whose bytes must be fetched
separately via ``users.messages.attachments.get``. This module walks that tree
once and produces a flat, typed :class:`~app.infra.google.types.ParsedEmail`.
"""

from __future__ import annotations

import base64
from typing import Any

from app.infra.google.types import EmailAttachmentMeta, ParsedEmail

_HEADERS_OF_INTEREST = ("Subject", "From", "To", "Cc", "Date")


def decode_base64url(data: str) -> bytes:
    """Decode Gmail's base64url body/attachment encoding (padding-tolerant)."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _headers_dict(headers: list[dict[str, Any]]) -> dict[str, str]:
    return {
        h["name"]: h["value"] for h in headers if h.get("name") in _HEADERS_OF_INTEREST
    }


def parse_message(message: dict[str, Any]) -> ParsedEmail:
    """Convert a raw ``users.messages.get`` (format=full) response.

    Args:
        message: The decoded JSON body of a Gmail ``messages.get`` call.

    Returns:
        A flattened, typed view: headers, decoded text/plain and text/html
        bodies (when present), and attachment metadata (without bytes).
    """
    payload: dict[str, Any] = message.get("payload", {})
    headers = _headers_dict(payload.get("headers", []) or [])

    text_plain: str | None = None
    text_html: str | None = None
    attachments: list[EmailAttachmentMeta] = []

    def walk(part: dict[str, Any]) -> None:
        nonlocal text_plain, text_html
        mime_type: str = part.get("mimeType", "")
        filename: str = part.get("filename") or ""
        body: dict[str, Any] = part.get("body", {}) or {}

        if filename and body.get("attachmentId"):
            attachments.append(
                EmailAttachmentMeta(
                    attachment_id=body["attachmentId"],
                    filename=filename,
                    mime_type=mime_type,
                    size=int(body.get("size", 0)),
                )
            )
        elif mime_type == "text/plain" and "data" in body and text_plain is None:
            text_plain = decode_base64url(body["data"]).decode(
                "utf-8", errors="replace"
            )
        elif mime_type == "text/html" and "data" in body and text_html is None:
            text_html = decode_base64url(body["data"]).decode("utf-8", errors="replace")

        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)

    return ParsedEmail(
        id=message["id"],
        thread_id=message.get("threadId", ""),
        label_ids=list(message.get("labelIds", []) or []),
        snippet=message.get("snippet", ""),
        subject=headers.get("Subject", ""),
        from_address=headers.get("From", ""),
        to_address=headers.get("To", ""),
        cc_address=headers.get("Cc", ""),
        date=headers.get("Date", ""),
        text_plain=text_plain,
        text_html=text_html,
        attachments=attachments,
    )
