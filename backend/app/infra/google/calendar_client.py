"""Google Calendar REST API client.

Talks to the ``calendars/primary/events`` resource to push locally-created
or AI-suggested calendar events to the user's primary Google Calendar (see
``app/services/calendar_sync_service.py``). Mirrors
:class:`~app.infra.google.gmail_client.GmailClient`'s structure: shared
rate limiter, :func:`~app.infra.google.http.send_with_retry` for
retry/backoff, and typed :class:`~app.core.exceptions.AppError` results
rather than raw ``httpx`` errors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config.settings import CalendarSettings
from app.core.exceptions import NotFoundError, UpstreamServiceError
from app.infra.google.http import send_with_retry
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.google.types import GoogleCalendarEvent


class GoogleCalendarClient:
    """Async client for the subset of the Google Calendar API this app uses.

    Args:
        http_client: The shared async HTTP client.
        settings: Calendar client configuration (base URL, timeouts, retries).
        access_token: A *valid, unexpired* OAuth access token.
        rate_limiter: Process-wide token bucket shared across all requests.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: CalendarSettings,
        access_token: str,
        rate_limiter: TokenBucketRateLimiter,
    ) -> None:
        self._http = http_client
        self._settings = settings
        self._base_url = f"{settings.api_base_url}/calendars/primary/events"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._rate_limiter = rate_limiter

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> httpx.Response:
        await self._rate_limiter.acquire()
        return await send_with_retry(
            self._http,
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            json=json_body,
            timeout=self._settings.request_timeout_seconds,
            max_attempts=self._settings.max_retries,
        )

    async def create_event(
        self,
        *,
        title: str,
        description: str,
        location: str,
        start_at: datetime,
        end_at: datetime,
    ) -> GoogleCalendarEvent:
        """Create a new event on the user's primary calendar (``events.insert``)."""
        response = await self._request(
            "POST",
            "",
            json_body=_event_payload(title, description, location, start_at, end_at),
        )
        _raise_for_unexpected(response)
        return _to_event(response.json())

    async def update_event(
        self,
        google_event_id: str,
        *,
        title: str,
        description: str,
        location: str,
        start_at: datetime,
        end_at: datetime,
    ) -> GoogleCalendarEvent:
        """Update an existing event (``events.patch``).

        Raises:
            NotFoundError: No event with this id exists (e.g. the user
                deleted it directly in Google Calendar).
        """
        response = await self._request(
            "PATCH",
            f"/{google_event_id}",
            json_body=_event_payload(title, description, location, start_at, end_at),
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(f"Calendar event {google_event_id!r} was not found.")
        _raise_for_unexpected(response)
        return _to_event(response.json())

    async def delete_event(self, google_event_id: str) -> None:
        """Delete an event (``events.delete``). A missing event is not an error."""
        response = await self._request("DELETE", f"/{google_event_id}")
        if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.GONE):
            return
        if response.status_code >= 400:
            _raise_for_unexpected(response)

    async def get_event(self, google_event_id: str) -> GoogleCalendarEvent:
        """Fetch a single event (``events.get``).

        Raises:
            NotFoundError: No event with this id exists.
        """
        response = await self._request("GET", f"/{google_event_id}")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(f"Calendar event {google_event_id!r} was not found.")
        _raise_for_unexpected(response)
        return _to_event(response.json())


def _event_payload(
    title: str, description: str, location: str, start_at: datetime, end_at: datetime
) -> dict[str, Any]:
    return {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_at.isoformat()},
        "end": {"dateTime": end_at.isoformat()},
    }


def _to_event(body: dict[str, Any]) -> GoogleCalendarEvent:
    return GoogleCalendarEvent(
        id=body["id"],
        status=body.get("status", "confirmed"),
        summary=body.get("summary", ""),
        description=body.get("description"),
        location=body.get("location"),
        start_at=datetime.fromisoformat(body["start"]["dateTime"]),
        end_at=datetime.fromisoformat(body["end"]["dateTime"]),
        html_link=body.get("htmlLink"),
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
