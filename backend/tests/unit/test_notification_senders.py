"""Unit tests for the individual notification-channel senders.

Each HTTP-based sender is driven against an ``httpx.MockTransport`` -- a
real request/response cycle through the sender's own code, just without a
real network call -- rather than mocking the sender's internals.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.config.settings import SMTPSettings, TelegramSettings, WhatsAppSettings
from app.services.notifications.discord import DiscordSender
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
)
from app.services.notifications.slack import SlackSender
from app.services.notifications.smtp_email import SMTPEmailSender
from app.services.notifications.telegram import TelegramSender
from app.services.notifications.webhook import WebhookSender
from app.services.notifications.whatsapp import WhatsAppSender


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_slack_sender_posts_text_to_webhook_url() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    async with _client(handler) as http_client:
        sender = SlackSender(http_client)
        await sender.send(
            title="Hi",
            body="there",
            config={"webhook_url": "https://hooks.slack.example/abc"},
        )

    assert captured["url"] == "https://hooks.slack.example/abc"
    assert "Hi" in json.loads(json.dumps(captured["body"]))["text"]


@pytest.mark.asyncio
async def test_slack_sender_missing_webhook_url_raises() -> None:
    async with _client(lambda r: httpx.Response(200)) as http_client:
        sender = SlackSender(http_client)
        with pytest.raises(ChannelDeliveryError):
            await sender.send(title="Hi", body="there", config={})


@pytest.mark.asyncio
async def test_slack_sender_raises_on_non_2xx() -> None:
    async with _client(lambda r: httpx.Response(500)) as http_client:
        sender = SlackSender(http_client)
        with pytest.raises(ChannelDeliveryError):
            await sender.send(
                title="Hi", body="there", config={"webhook_url": "https://x.test"}
            )


@pytest.mark.asyncio
async def test_discord_sender_posts_content_to_webhook_url() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    async with _client(handler) as http_client:
        sender = DiscordSender(http_client)
        await sender.send(
            title="Hi",
            body="there",
            config={"webhook_url": "https://discord.example/abc"},
        )

    assert "Hi" in json.loads(json.dumps(captured["body"]))["content"]


@pytest.mark.asyncio
async def test_telegram_sender_not_configured_without_bot_token() -> None:
    async with _client(lambda r: httpx.Response(200)) as http_client:
        sender = TelegramSender(http_client, TelegramSettings(bot_token=""))
        with pytest.raises(ChannelNotConfiguredError):
            await sender.send(title="Hi", body="there", config={"chat_id": "123"})


@pytest.mark.asyncio
async def test_telegram_sender_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "bottest-token" in str(request.url)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as http_client:
        sender = TelegramSender(http_client, TelegramSettings(bot_token="test-token"))
        await sender.send(title="Hi", body="there", config={"chat_id": "123"})


@pytest.mark.asyncio
async def test_telegram_sender_raises_when_response_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "bad chat id"})

    async with _client(handler) as http_client:
        sender = TelegramSender(http_client, TelegramSettings(bot_token="test-token"))
        with pytest.raises(ChannelDeliveryError):
            await sender.send(title="Hi", body="there", config={"chat_id": "123"})


@pytest.mark.asyncio
async def test_whatsapp_sender_not_configured_without_twilio_credentials() -> None:
    async with _client(lambda r: httpx.Response(200)) as http_client:
        sender = WhatsAppSender(http_client, WhatsAppSettings())
        with pytest.raises(ChannelNotConfiguredError):
            await sender.send(
                title="Hi", body="there", config={"to_number": "+15551234567"}
            )


@pytest.mark.asyncio
async def test_whatsapp_sender_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"sid": "SM123"})

    settings = WhatsAppSettings(
        twilio_account_sid="AC123",
        twilio_auth_token="secret",
        from_number="whatsapp:+14155238886",
    )
    async with _client(handler) as http_client:
        sender = WhatsAppSender(http_client, settings)
        await sender.send(
            title="Hi", body="there", config={"to_number": "+15551234567"}
        )


@pytest.mark.asyncio
async def test_webhook_sender_signs_payload_when_secret_present() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200)

    async with _client(handler) as http_client:
        sender = WebhookSender(http_client)
        await sender.send(
            title="Hi",
            body="there",
            config={"url": "https://example.test/hook", "secret": "shh"},
        )

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-aeea-signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_webhook_sender_omits_signature_without_secret() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200)

    async with _client(handler) as http_client:
        sender = WebhookSender(http_client)
        await sender.send(
            title="Hi", body="there", config={"url": "https://example.test/hook"}
        )

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "x-aeea-signature" not in headers


@pytest.mark.asyncio
async def test_smtp_sender_not_configured_without_host() -> None:
    sender = SMTPEmailSender(SMTPSettings())
    with pytest.raises(ChannelNotConfiguredError):
        await sender.send(
            title="Hi", body="there", config={"to_address": "a@example.com"}
        )


@pytest.mark.asyncio
async def test_smtp_sender_sends_via_aiosmtplib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_send(
        message: object, **kwargs: object
    ) -> tuple[dict[str, object], str]:
        calls.append({"message": message, **kwargs})
        return {}, "OK"

    import app.services.notifications.smtp_email as smtp_module

    monkeypatch.setattr(smtp_module.aiosmtplib, "send", fake_send)

    settings = SMTPSettings(
        host="smtp.example.com", from_address="assistant@example.com"
    )
    sender = SMTPEmailSender(settings)
    await sender.send(title="Hi", body="there", config={"to_address": "a@example.com"})

    assert len(calls) == 1
    assert calls[0]["hostname"] == "smtp.example.com"
