"""Unit tests for the desktop (Web Push) and mobile (FCM) push channels.

``pywebpush.webpush`` performs a real synchronous HTTP POST (built on
``requests``, not an injectable async client) and FCM token minting calls
Google's real OAuth token-refresh endpoint -- neither has an injectable
transport the way every other channel sender in this codebase does (see
``tests/unit/test_notification_senders.py``, all of which fake the HTTP
layer via ``httpx.ASGITransport``). These two therefore fake at the
narrowest real boundary instead: the third-party call itself
(``pywebpush.webpush`` and ``MobilePushSender._get_access_token``), exactly
mirroring how the rest of the suite builds real fake doubles for
third-party services rather than mocking this codebase's own internals.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.config.settings import PushSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
    DeviceUnregisteredError,
)
from app.services.notifications.push_desktop import DesktopPushSender
from app.services.notifications.push_mobile import MobilePushSender
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def _desktop_settings(*, configured: bool = True) -> PushSettings:
    if not configured:
        return PushSettings()
    return PushSettings(
        vapid_private_key="test-private-key", vapid_public_key="test-public-key"
    )


def _device_config() -> dict[str, Any]:
    return {
        "endpoint": "https://push.example.com/subscription/abc",
        "keys": {"p256dh": "key", "auth": "secret"},
    }


class _FakeWebPushResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@pytest.mark.asyncio
async def test_desktop_push_raises_when_not_configured() -> None:
    sender = DesktopPushSender(_desktop_settings(configured=False))
    with pytest.raises(ChannelNotConfiguredError):
        await sender.send(title="T", body="B", device_config=_device_config())


@pytest.mark.asyncio
async def test_desktop_push_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.notifications.push_desktop as module

    calls: list[dict[str, Any]] = []

    def _fake_webpush(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(module, "webpush", _fake_webpush)
    sender = DesktopPushSender(_desktop_settings())
    await sender.send(title="Hello", body="World", device_config=_device_config())

    assert len(calls) == 1
    assert calls[0]["vapid_claims"] == {"sub": "mailto:notifications@example.com"}


@pytest.mark.asyncio
async def test_desktop_push_raises_device_unregistered_on_410(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.notifications.push_desktop as module

    def _fake_webpush(**kwargs: Any) -> None:
        raise module.WebPushException("gone", response=_FakeWebPushResponse(410))

    monkeypatch.setattr(module, "webpush", _fake_webpush)
    sender = DesktopPushSender(_desktop_settings())
    with pytest.raises(DeviceUnregisteredError):
        await sender.send(title="T", body="B", device_config=_device_config())


@pytest.mark.asyncio
async def test_desktop_push_raises_channel_delivery_error_on_other_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.notifications.push_desktop as module

    def _fake_webpush(**kwargs: Any) -> None:
        raise module.WebPushException(
            "server error", response=_FakeWebPushResponse(500)
        )

    monkeypatch.setattr(module, "webpush", _fake_webpush)
    sender = DesktopPushSender(_desktop_settings())
    with pytest.raises(ChannelDeliveryError):
        await sender.send(title="T", body="B", device_config=_device_config())


@pytest.mark.asyncio
async def test_desktop_push_raises_channel_delivery_error_with_no_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.notifications.push_desktop as module

    def _fake_webpush(**kwargs: Any) -> None:
        raise module.WebPushException("network error", response=None)

    monkeypatch.setattr(module, "webpush", _fake_webpush)
    sender = DesktopPushSender(_desktop_settings())
    with pytest.raises(ChannelDeliveryError):
        await sender.send(title="T", body="B", device_config=_device_config())


def _mobile_settings(*, configured: bool = True) -> PushSettings:
    if not configured:
        return PushSettings()
    return PushSettings(fcm_service_account_json="{}", fcm_project_id="test-project")


def _mobile_device_config() -> dict[str, Any]:
    return {"fcm_token": "device-token-abc"}


def _patch_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``_get_access_token`` is sync (run via asyncio.to_thread in send()) --
    # patch it directly so tests never touch google-auth's real network
    # token-refresh call.
    monkeypatch.setattr(
        MobilePushSender, "_get_access_token", lambda self: "fake-access-token"
    )


@pytest.mark.asyncio
async def test_mobile_push_raises_when_not_configured() -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=Starlette(routes=[]))
    ) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings(configured=False))
        with pytest.raises(ChannelNotConfiguredError):
            await sender.send(
                title="T", body="B", device_config=_mobile_device_config()
            )


@pytest.mark.asyncio
async def test_mobile_push_raises_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access_token(monkeypatch)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=Starlette(routes=[]))
    ) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        with pytest.raises(ChannelDeliveryError):
            await sender.send(title="T", body="B", device_config={})


@pytest.mark.asyncio
async def test_mobile_push_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_access_token(monkeypatch)

    async def _fcm_ok(request: Request) -> JSONResponse:
        assert request.headers["authorization"] == "Bearer fake-access-token"
        return JSONResponse({"name": "projects/test-project/messages/1"})

    app = Starlette(
        routes=[
            Route("/v1/projects/{project_id}/messages:send", _fcm_ok, methods=["POST"])
        ]
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app)) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        await sender.send(
            title="Hello", body="World", device_config=_mobile_device_config()
        )


@pytest.mark.asyncio
async def test_mobile_push_raises_device_unregistered_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access_token(monkeypatch)

    async def _fcm_404(request: Request) -> JSONResponse:
        return JSONResponse({"error": {"status": "NOT_FOUND"}}, status_code=404)

    app = Starlette(
        routes=[
            Route("/v1/projects/{project_id}/messages:send", _fcm_404, methods=["POST"])
        ]
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app)) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        with pytest.raises(DeviceUnregisteredError):
            await sender.send(
                title="T", body="B", device_config=_mobile_device_config()
            )


@pytest.mark.asyncio
async def test_mobile_push_raises_device_unregistered_on_unregistered_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access_token(monkeypatch)

    async def _fcm_unregistered(request: Request) -> JSONResponse:
        return JSONResponse({"error": {"status": "UNREGISTERED"}}, status_code=400)

    app = Starlette(
        routes=[
            Route(
                "/v1/projects/{project_id}/messages:send",
                _fcm_unregistered,
                methods=["POST"],
            )
        ]
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app)) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        with pytest.raises(DeviceUnregisteredError):
            await sender.send(
                title="T", body="B", device_config=_mobile_device_config()
            )


@pytest.mark.asyncio
async def test_mobile_push_raises_channel_delivery_error_on_other_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access_token(monkeypatch)

    async def _fcm_error(request: Request) -> JSONResponse:
        return JSONResponse({"error": {"status": "INTERNAL"}}, status_code=500)

    app = Starlette(
        routes=[
            Route(
                "/v1/projects/{project_id}/messages:send",
                _fcm_error,
                methods=["POST"],
            )
        ]
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app)) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        with pytest.raises(ChannelDeliveryError):
            await sender.send(
                title="T", body="B", device_config=_mobile_device_config()
            )


@pytest.mark.asyncio
async def test_mobile_push_raises_channel_delivery_error_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access_token(monkeypatch)

    class _BrokenTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=_BrokenTransport()) as http_client:
        sender = MobilePushSender(http_client, _mobile_settings())
        with pytest.raises(ChannelDeliveryError):
            await sender.send(
                title="T", body="B", device_config=_mobile_device_config()
            )
