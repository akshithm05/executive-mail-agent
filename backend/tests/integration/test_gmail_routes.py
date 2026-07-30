"""Integration tests for the Gmail routes.

Driven over real HTTP through the logged-in session (``logged_in_client``),
against the fake Gmail server -- exercising profile, labels, message
reading/parsing, attachment download, and search pagination end to end.
"""

from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient

from tests.fake_google.app import ATTACHMENT_BYTES


@pytest.mark.asyncio
async def test_get_profile(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get("/api/v1/gmail/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["email_address"] == "exec@example.com"
    assert body["messages_total"] == 2


@pytest.mark.asyncio
async def test_gmail_routes_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/gmail/profile")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_list_labels(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get("/api/v1/gmail/labels")

    assert response.status_code == 200
    names = {label["name"] for label in response.json()["labels"]}
    assert {"INBOX", "Work"}.issubset(names)


@pytest.mark.asyncio
async def test_create_label(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.post(
        "/api/v1/gmail/labels", json={"name": "Personal"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Personal"
    assert body["type"] == "user"

    listed = await logged_in_client.get("/api/v1/gmail/labels")
    assert "Personal" in {label["name"] for label in listed.json()["labels"]}


@pytest.mark.asyncio
async def test_create_label_conflict_on_duplicate_name(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.post(
        "/api/v1/gmail/labels", json={"name": "Work"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


@pytest.mark.asyncio
async def test_get_message_reads_body_and_attachment_metadata(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.get("/api/v1/gmail/messages/msg-2")

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "Invoice #1042"
    assert body["from_address"] == "Billing <billing@example.com>"
    assert body["text_plain"] == "Please find the invoice attached."
    assert body["text_html"] == "<p>Please find the invoice attached.</p>"
    assert len(body["attachments"]) == 1
    attachment = body["attachments"][0]
    assert attachment["attachment_id"] == "att-1042"
    assert attachment["filename"] == "invoice-1042.pdf"
    assert attachment["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_get_message_not_found(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get("/api/v1/gmail/messages/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_attachment_returns_original_bytes(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.get(
        "/api/v1/gmail/messages/msg-2/attachments/att-1042"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["size"] == len(ATTACHMENT_BYTES)
    assert base64.b64decode(body["data_base64"]) == ATTACHMENT_BYTES


@pytest.mark.asyncio
async def test_get_attachment_not_found(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get(
        "/api/v1/gmail/messages/msg-2/attachments/does-not-exist"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_messages_paginates(logged_in_client: AsyncClient) -> None:
    first_page = await logged_in_client.get(
        "/api/v1/gmail/messages", params={"maxResults": 1}
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["messages"]) == 1
    assert first_body["messages"][0]["id"] == "msg-1"
    assert first_body["next_page_token"] == "1"

    second_page = await logged_in_client.get(
        "/api/v1/gmail/messages",
        params={"maxResults": 1, "pageToken": first_body["next_page_token"]},
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["messages"]) == 1
    assert second_body["messages"][0]["id"] == "msg-2"
    assert second_body["next_page_token"] is None


@pytest.mark.asyncio
async def test_search_messages_filters_by_query(logged_in_client: AsyncClient) -> None:
    response = await logged_in_client.get(
        "/api/v1/gmail/messages", params={"q": "is:unread"}
    )

    assert response.status_code == 200
    body = response.json()
    assert [m["id"] for m in body["messages"]] == ["msg-1"]
    assert body["result_size_estimate"] == 1
