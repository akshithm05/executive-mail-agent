"""Mobile push notification channel: Firebase Cloud Messaging, HTTP v1 API.

FCM's legacy server-key API was retired; the current HTTP v1 API requires an
OAuth2 access token minted from a service-account credential. Minting/
refreshing that token via ``google-auth`` is a synchronous, blocking call,
so it is offloaded to a worker thread via ``asyncio.to_thread``; the actual
send is a plain ``httpx`` POST.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from app.config.settings import PushSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
    DeviceUnregisteredError,
)

REQUIRED_DEVICE_FIELDS = ("fcm_token",)

_FCM_SCOPES = ("https://www.googleapis.com/auth/firebase.messaging",)


class MobilePushSender:
    """Sends one push notification to one FCM device token."""

    def __init__(self, http_client: httpx.AsyncClient, settings: PushSettings) -> None:
        self._http = http_client
        self._settings = settings
        self._credentials: service_account.Credentials | None = None

    async def send(
        self, *, title: str, body: str, device_config: dict[str, Any]
    ) -> None:
        """Push ``title``/``body`` to the FCM token in ``device_config``.

        Raises:
            ChannelNotConfiguredError: No FCM service account is configured.
            DeviceUnregisteredError: FCM reports the token no longer exists
                -- the caller should deactivate this device rather than
                retry.
            ChannelDeliveryError: Any other delivery failure.
        """
        if not self._settings.is_mobile_configured:
            raise ChannelNotConfiguredError("Mobile push (FCM) is not configured.")

        fcm_token = device_config.get("fcm_token")
        if not fcm_token:
            raise ChannelDeliveryError(
                "Mobile push device config is missing 'fcm_token'."
            )

        access_token = await asyncio.to_thread(self._get_access_token)
        url = (
            f"https://fcm.googleapis.com/v1/projects/"
            f"{self._settings.fcm_project_id}/messages:send"
        )
        payload = {
            "message": {
                "token": fcm_token,
                "notification": {"title": title, "body": body},
            }
        }
        try:
            response = await self._http.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"FCM request failed: {exc}") from exc

        if response.status_code < 400:
            return

        if _is_unregistered(response):
            raise DeviceUnregisteredError(
                "FCM reports this device token is unregistered."
            )
        raise ChannelDeliveryError(
            f"FCM send returned {response.status_code}: {response.text[:500]}"
        )

    def _get_access_token(self) -> str:
        if self._credentials is None:
            info = json.loads(self._settings.fcm_service_account_json)
            self._credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                info, scopes=list(_FCM_SCOPES)
            )
        if not self._credentials.valid:
            self._credentials.refresh(GoogleAuthRequest())
        return str(self._credentials.token)


def _is_unregistered(response: httpx.Response) -> bool:
    if response.status_code == httpx.codes.NOT_FOUND:
        return True
    try:
        status = response.json().get("error", {}).get("status")
    except ValueError:
        return False
    return bool(status == "UNREGISTERED")
