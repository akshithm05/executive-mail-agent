"""Tests for Gmail MIME payload parsing."""

import base64

from app.infra.google.mime_parser import decode_base64url, parse_message


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def test_decode_base64url_handles_missing_padding() -> None:
    # "hello" base64url-encodes to "aGVsbG8" (no padding needed here), but
    # Gmail commonly omits the '=' padding characters even when required.
    encoded = base64.urlsafe_b64encode(b"hello!!").decode("ascii").rstrip("=")
    assert decode_base64url(encoded) == b"hello!!"


def test_parse_message_extracts_headers_and_multipart_body() -> None:
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hello there",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Test subject"},
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Cc", "value": "carol@example.com"},
                {"name": "Date", "value": "Mon, 27 Jul 2026 10:00:00 -0700"},
                {"name": "X-Ignored-Header", "value": "should not appear"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64url("Plain body")}},
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url("<p>HTML body</p>")},
                },
            ],
        },
    }

    parsed = parse_message(message)

    assert parsed.id == "msg-1"
    assert parsed.thread_id == "thread-1"
    assert parsed.label_ids == ["INBOX", "UNREAD"]
    assert parsed.subject == "Test subject"
    assert parsed.from_address == "alice@example.com"
    assert parsed.to_address == "bob@example.com"
    assert parsed.cc_address == "carol@example.com"
    assert parsed.text_plain == "Plain body"
    assert parsed.text_html == "<p>HTML body</p>"
    assert parsed.attachments == []


def test_parse_message_extracts_nested_attachment() -> None:
    message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["INBOX"],
        "snippet": "See attached",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Invoice"}],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64url("Body")}},
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice.pdf",
                    "body": {"attachmentId": "att-1", "size": 4096},
                },
            ],
        },
    }

    parsed = parse_message(message)

    assert parsed.text_plain == "Body"
    assert len(parsed.attachments) == 1
    attachment = parsed.attachments[0]
    assert attachment.attachment_id == "att-1"
    assert attachment.filename == "invoice.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size == 4096


def test_parse_message_handles_single_part_top_level_payload() -> None:
    # Simple messages have no `parts` at all: the body is directly on payload.
    message = {
        "id": "msg-3",
        "threadId": "thread-3",
        "labelIds": [],
        "snippet": "Just text",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "Simple"}],
            "body": {"data": _b64url("Just a plain body, no parts.")},
        },
    }

    parsed = parse_message(message)

    assert parsed.text_plain == "Just a plain body, no parts."
    assert parsed.text_html is None
    assert parsed.attachments == []
