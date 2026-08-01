"""Integration tests for notification-config endpoints.

Covers channels, custom rules, quiet hours, and push-device registration.
"""

from __future__ import annotations

from datetime import time

import pytest
from app.infra.db.session import Database
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)
from app.infra.repositories.push_device import PushDeviceRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


@pytest.mark.asyncio
async def test_channel_config_routes_require_authentication(
    client: AsyncClient,
) -> None:
    assert (await client.get("/api/v1/notification-channels")).status_code == 401
    assert (
        await client.put("/api/v1/notification-channels/slack", json={"config": {}})
    ).status_code == 401


@pytest.mark.asyncio
async def test_set_and_list_channel_config_never_leaks_the_secret(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.put(
        "/api/v1/notification-channels/slack",
        json={
            "config": {"webhook_url": "https://hooks.slack.example/abc"},
            "is_enabled": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["channel_type"] == "slack"
    assert body["is_enabled"] is True
    assert "webhook_url" not in body
    assert "config" not in body

    list_response = await logged_in_client.get("/api/v1/notification-channels")
    assert list_response.status_code == 200
    channels = list_response.json()
    assert any(c["channel_type"] == "slack" for c in channels)


@pytest.mark.asyncio
async def test_set_channel_config_rejects_missing_required_field(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.put(
        "/api/v1/notification-channels/slack", json={"config": {}}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_set_channel_config_rejects_unknown_channel_type(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.put(
        "/api/v1/notification-channels/carrier-pigeon", json={"config": {"x": "y"}}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_channel_config(
    logged_in_client: AsyncClient, database: Database
) -> None:
    await logged_in_client.put(
        "/api/v1/notification-channels/webhook",
        json={"config": {"url": "https://x.test"}},
    )
    delete_response = await logged_in_client.delete(
        "/api/v1/notification-channels/webhook"
    )
    assert delete_response.status_code == 204

    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        remaining = await NotificationChannelConfigRepository(session).list_by_user(
            user.id
        )
        assert remaining == []


@pytest.mark.asyncio
async def test_delete_missing_channel_config_returns_404(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.delete("/api/v1/notification-channels/telegram")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_list_update_delete_notification_rule(
    logged_in_client: AsyncClient,
) -> None:
    create_response = await logged_in_client.post(
        "/api/v1/notification-rules",
        json={"name": "Important only", "only_important": True},
    )
    assert create_response.status_code == 200
    rule = create_response.json()
    assert rule["only_important"] is True
    assert rule["is_enabled"] is True

    list_response = await logged_in_client.get("/api/v1/notification-rules")
    assert len(list_response.json()) == 1

    update_response = await logged_in_client.patch(
        f"/api/v1/notification-rules/{rule['id']}", json={"is_enabled": False}
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_enabled"] is False
    assert update_response.json()["only_important"] is True  # untouched fields survive

    delete_response = await logged_in_client.delete(
        f"/api/v1/notification-rules/{rule['id']}"
    )
    assert delete_response.status_code == 204
    assert (await logged_in_client.get("/api/v1/notification-rules")).json() == []


@pytest.mark.asyncio
async def test_notification_rule_routes_require_authentication(
    client: AsyncClient,
) -> None:
    response = await client.delete(
        "/api/v1/notification-rules/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_notification_rule_ownership_check_returns_404_for_other_tenant(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.patch(
        "/api/v1/notification-rules/00000000-0000-0000-0000-000000000000",
        json={"is_enabled": False},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_quiet_hours_defaults_to_null_until_configured(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.get("/api/v1/quiet-hours")
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_set_and_get_quiet_hours(logged_in_client: AsyncClient) -> None:
    set_response = await logged_in_client.put(
        "/api/v1/quiet-hours",
        json={
            "is_enabled": True,
            "start_time": "22:00:00",
            "end_time": "07:00:00",
            "timezone": "America/New_York",
            "allow_urgent_override": False,
        },
    )
    assert set_response.status_code == 200
    body = set_response.json()
    assert body["is_enabled"] is True
    assert body["timezone"] == "America/New_York"
    assert body["allow_urgent_override"] is False

    get_response = await logged_in_client.get("/api/v1/quiet-hours")
    assert get_response.json()["timezone"] == "America/New_York"

    # A second PUT upserts rather than creating a duplicate row.
    second_response = await logged_in_client.put(
        "/api/v1/quiet-hours",
        json={
            "is_enabled": False,
            "start_time": str(time(21, 0)),
            "end_time": str(time(6, 0)),
            "timezone": "UTC",
        },
    )
    assert second_response.json()["id"] == body["id"]
    assert second_response.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_register_list_and_delete_push_device(
    logged_in_client: AsyncClient, database: Database
) -> None:
    register_response = await logged_in_client.post(
        "/api/v1/push-devices",
        json={
            "platform": "web",
            "config": {
                "endpoint": "https://push.example/abc",
                "keys": {"p256dh": "key", "auth": "secret"},
            },
        },
    )
    assert register_response.status_code == 200
    device = register_response.json()
    assert device["platform"] == "web"
    assert "endpoint" not in device

    list_response = await logged_in_client.get("/api/v1/push-devices")
    assert len(list_response.json()) == 1

    delete_response = await logged_in_client.delete(
        f"/api/v1/push-devices/{device['id']}"
    )
    assert delete_response.status_code == 204

    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        remaining = await PushDeviceRepository(session).list_by_user(user.id)
        assert remaining == []


@pytest.mark.asyncio
async def test_register_push_device_rejects_missing_required_field(
    logged_in_client: AsyncClient,
) -> None:
    response = await logged_in_client.post(
        "/api/v1/push-devices", json={"platform": "ios", "config": {}}
    )
    assert response.status_code == 422
