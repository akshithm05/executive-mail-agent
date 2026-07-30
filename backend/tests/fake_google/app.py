"""Fake Google OAuth + Gmail API server for tests.

Routes match Google's real paths (only the host is swapped out via
``httpx.ASGITransport``, see ``tests/conftest.py``):

* ``POST /token`` -- authorization_code and refresh_token grants.
* ``GET /v1/userinfo`` -- OpenID Connect identity.
* ``POST /revoke`` -- token revocation.
* ``GET /gmail/v1/users/me/profile``
* ``GET|POST /gmail/v1/users/me/labels``
* ``GET /gmail/v1/users/me/messages`` (search + ``pageToken`` pagination)
* ``GET /gmail/v1/users/me/messages/{id}``
* ``GET /gmail/v1/users/me/messages/{id}/attachments/{attachment_id}``
* ``POST /calendar/v3/calendars/primary/events``
* ``GET|PATCH|DELETE /calendar/v3/calendars/primary/events/{event_id}``

Retry/backoff behavior is tested separately, directly against
``app.infra.google.http.send_with_retry`` (see
``tests/unit/test_http_retry.py``), using a minimal purpose-built flaky ASGI
app -- that is the right level to assert attempt counts and backoff, and
keeps this double focused on faithfully modeling Google's actual endpoints.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

VALID_AUTH_CODE = "valid-auth-code"
GOOGLE_SUBJECT = "google-user-123"
USER_EMAIL = "exec@example.com"
USER_NAME = "Executive User"
USER_PICTURE = "https://example.com/avatar.png"
GRANTED_SCOPE = (
    "openid email profile "
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.labels"
)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


ATTACHMENT_BYTES = b"%PDF-1.4 fake invoice content for testing only"

_MESSAGES: dict[str, dict[str, Any]] = {
    "msg-1": {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hi team, here are this week's notes...",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Weekly sync notes"},
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "exec@example.com"},
                {"name": "Date", "value": "Mon, 27 Jul 2026 10:00:00 -0700"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("Hi team, here are this week's notes.")},
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": _b64url("<p>Hi team, here are this week's notes.</p>")
                    },
                },
            ],
        },
    },
    "msg-2": {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["INBOX"],
        "snippet": "Please see the attached invoice.",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Invoice #1042"},
                {"name": "From", "value": "Billing <billing@example.com>"},
                {"name": "To", "value": "exec@example.com"},
                {"name": "Date", "value": "Tue, 28 Jul 2026 09:15:00 -0700"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": _b64url("Please find the invoice attached.")
                            },
                        },
                        {
                            "mimeType": "text/html",
                            "body": {
                                "data": _b64url(
                                    "<p>Please find the invoice attached.</p>"
                                )
                            },
                        },
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice-1042.pdf",
                    "body": {
                        "attachmentId": "att-1042",
                        "size": len(ATTACHMENT_BYTES),
                    },
                },
            ],
        },
    },
    # HTML-only body (no text/plain part) -- exercises the BeautifulSoup
    # plain-text fallback in the ingestion pipeline. Deliberately excluded
    # from _MESSAGE_ORDER so it does not affect the search/pagination and
    # profile message-count tests, which assume exactly two messages.
    "msg-3": {
        "id": "msg-3",
        "threadId": "thread-3",
        "labelIds": ["INBOX"],
        "snippet": "Special offer inside",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "Subject", "value": "Newsletter"},
                {"name": "From", "value": "news@example.com"},
                {"name": "To", "value": "exec@example.com"},
                {"name": "Date", "value": "Wed, 29 Jul 2026 08:00:00 -0700"},
            ],
            "body": {
                "data": _b64url(
                    "<html><body><script>track();</script>"
                    "<h1>Big Sale</h1><p>Save <b>20%</b> today.</p>"
                    "</body></html>"
                )
            },
        },
    },
}
_MESSAGE_ORDER = ["msg-1", "msg-2"]
_ATTACHMENTS = {"att-1042": ATTACHMENT_BYTES}


class FakeGoogleState:
    """Mutable state for one fake-server instance (fresh per test)."""

    def __init__(self) -> None:
        self.unused_codes: set[str] = {VALID_AUTH_CODE}
        self.access_tokens: dict[str, str] = {}  # token -> google_subject
        self.refresh_tokens: dict[str, str] = {}  # token -> google_subject
        self.revoked_tokens: set[str] = set()
        self.labels: dict[str, dict[str, Any]] = {
            "INBOX": {"id": "INBOX", "name": "INBOX", "type": "system"},
            "Work": {
                "id": "Label_1",
                "name": "Work",
                "type": "user",
                "messageListVisibility": "show",
                "labelListVisibility": "labelShow",
            },
        }
        self._next_label_id = 2
        self.token_endpoint_calls = 0
        self.calendar_events: dict[str, dict[str, Any]] = {}
        self._next_event_id = 1

    def next_event_id(self) -> str:
        """Return the next unique Google Calendar event id."""
        event_id = f"event-{self._next_event_id}"
        self._next_event_id += 1
        return event_id

    def issue_token_pair(self, subject: str) -> tuple[str, str]:
        """Issue a fresh (access_token, refresh_token) pair for a subject."""
        access_token = f"access-{uuid.uuid4().hex[:12]}"
        refresh_token = f"refresh-{uuid.uuid4().hex[:12]}"
        self.access_tokens[access_token] = subject
        self.refresh_tokens[refresh_token] = subject
        return access_token, refresh_token

    def issue_access_token(self, subject: str) -> str:
        """Issue a fresh access token for a subject (refresh-grant response)."""
        access_token = f"access-{uuid.uuid4().hex[:12]}"
        self.access_tokens[access_token] = subject
        return access_token

    def next_label_id(self) -> str:
        """Return the next unique label id, e.g. ``Label_2``."""
        label_id = f"Label_{self._next_label_id}"
        self._next_label_id += 1
        return label_id


def _bearer_subject(state: FakeGoogleState, authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    if token in state.revoked_tokens:
        return None
    return state.access_tokens.get(token)


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": {"message": "Invalid Credentials"}}, status_code=401)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)


def create_fake_google_app() -> FastAPI:
    """Build a fresh fake Google app with isolated in-memory state."""
    app = FastAPI(title="fake-google")
    state = FakeGoogleState()
    app.state.fake_google = state

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        state.token_endpoint_calls += 1
        form = await request.form()
        grant_type = form.get("grant_type")

        if grant_type == "authorization_code":
            code = form.get("code")
            if code not in state.unused_codes:
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "Bad or reused code.",
                    },
                    status_code=400,
                )
            state.unused_codes.discard(str(code))
            access_token, refresh_token = state.issue_token_pair(GOOGLE_SUBJECT)
            return JSONResponse(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": 3600,
                    "scope": GRANTED_SCOPE,
                    "token_type": "Bearer",
                    "id_token": "fake-id-token",
                }
            )

        if grant_type == "refresh_token":
            refresh_token = str(form.get("refresh_token"))
            subject = state.refresh_tokens.get(refresh_token)
            if subject is None or refresh_token in state.revoked_tokens:
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "Refresh token revoked.",
                    },
                    status_code=400,
                )
            access_token = state.issue_access_token(subject)
            return JSONResponse(
                {
                    "access_token": access_token,
                    "expires_in": 3600,
                    "scope": GRANTED_SCOPE,
                    "token_type": "Bearer",
                }
            )

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    @app.get("/v1/userinfo")
    async def userinfo(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        subject = _bearer_subject(state, authorization)
        if subject is None:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse(
            {
                "sub": subject,
                "email": USER_EMAIL,
                "email_verified": True,
                "name": USER_NAME,
                "picture": USER_PICTURE,
            }
        )

    @app.post("/revoke")
    async def revoke(request: Request) -> JSONResponse:
        form = await request.form()
        token_value = str(form.get("token", ""))
        state.revoked_tokens.add(token_value)
        return JSONResponse({})

    @app.get("/gmail/v1/users/me/profile")
    async def gmail_profile(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        return JSONResponse(
            {
                "emailAddress": USER_EMAIL,
                "messagesTotal": len(_MESSAGE_ORDER),
                "threadsTotal": len(_MESSAGE_ORDER),
                "historyId": "1000",
            }
        )

    @app.get("/gmail/v1/users/me/labels")
    async def list_labels(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        return JSONResponse({"labels": list(state.labels.values())})

    @app.post("/gmail/v1/users/me/labels")
    async def create_label(
        request: Request, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        body = await request.json()
        name = body.get("name", "")
        if name in state.labels:
            return JSONResponse(
                {"error": {"code": 409, "message": "Label name exists or conflicts"}},
                status_code=409,
            )
        label = {
            "id": state.next_label_id(),
            "name": name,
            "type": "user",
            "messageListVisibility": body.get("messageListVisibility", "show"),
            "labelListVisibility": body.get("labelListVisibility", "labelShow"),
        }
        state.labels[name] = label
        return JSONResponse(label)

    @app.get("/gmail/v1/users/me/messages")
    async def search_messages(
        authorization: str | None = Header(default=None),
        q: str | None = None,
        pageToken: str | None = None,  # noqa: N803 - Gmail's actual query param name
        maxResults: int = 25,  # noqa: N803 - Gmail's actual query param name
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()

        candidate_ids = list(_MESSAGE_ORDER)
        if q and "is:unread" in q:
            candidate_ids = [
                mid for mid in candidate_ids if "UNREAD" in _MESSAGES[mid]["labelIds"]
            ]

        start = int(pageToken) if pageToken else 0
        page_ids = candidate_ids[start : start + maxResults]
        next_index = start + maxResults
        next_page_token = str(next_index) if next_index < len(candidate_ids) else None

        return JSONResponse(
            {
                "messages": [
                    {"id": mid, "threadId": _MESSAGES[mid]["threadId"]}
                    for mid in page_ids
                ],
                "nextPageToken": next_page_token,
                "resultSizeEstimate": len(candidate_ids),
            }
        )

    @app.get("/gmail/v1/users/me/messages/{message_id}")
    async def get_message(
        message_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        message = _MESSAGES.get(message_id)
        if message is None:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        return JSONResponse(message)

    @app.get("/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}")
    async def get_attachment(
        message_id: str,
        attachment_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        if message_id not in _MESSAGES or attachment_id not in _ATTACHMENTS:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        raw = _ATTACHMENTS[attachment_id]
        return JSONResponse(
            {
                "attachmentId": attachment_id,
                "size": len(raw),
                "data": base64.urlsafe_b64encode(raw).decode("ascii"),
            }
        )

    @app.post("/calendar/v3/calendars/primary/events")
    async def create_calendar_event(
        request: Request, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        body = await request.json()
        event_id = state.next_event_id()
        event = {
            "id": event_id,
            "status": "confirmed",
            "summary": body.get("summary", ""),
            "description": body.get("description", ""),
            "location": body.get("location", ""),
            "start": body["start"],
            "end": body["end"],
            "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
        }
        state.calendar_events[event_id] = event
        return JSONResponse(event, status_code=200)

    @app.get("/calendar/v3/calendars/primary/events/{event_id}")
    async def get_calendar_event(
        event_id: str, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        event = state.calendar_events.get(event_id)
        if event is None:
            return _not_found()
        return JSONResponse(event)

    @app.patch("/calendar/v3/calendars/primary/events/{event_id}")
    async def update_calendar_event(
        event_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        event = state.calendar_events.get(event_id)
        if event is None:
            return _not_found()
        body = await request.json()
        event.update(
            {
                "summary": body.get("summary", event["summary"]),
                "description": body.get("description", event["description"]),
                "location": body.get("location", event["location"]),
                "start": body.get("start", event["start"]),
                "end": body.get("end", event["end"]),
            }
        )
        return JSONResponse(event)

    @app.delete("/calendar/v3/calendars/primary/events/{event_id}")
    async def delete_calendar_event(
        event_id: str, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        if _bearer_subject(state, authorization) is None:
            return _unauthorized()
        state.calendar_events.pop(event_id, None)
        return JSONResponse({}, status_code=204)

    return app
