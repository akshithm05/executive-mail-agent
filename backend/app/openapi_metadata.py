"""Static OpenAPI/Swagger presentation metadata.

Kept separate from :func:`app.main.create_app` so the composition root isn't
cluttered with prose -- everything here is descriptive text and tag
ordering, not application wiring. ``API_DESCRIPTION`` renders at the top of
``/docs`` (Swagger UI) and ``/redoc``; ``OPENAPI_TAGS`` controls the order
and per-section descriptions of the left-hand navigation on both.
"""

from __future__ import annotations

API_DESCRIPTION = """
Backend API for the **AI Executive Email Assistant** -- an AI-powered
executive assistant that triages Gmail, extracts tasks and deadlines,
drafts replies, and surfaces a daily briefing.

## Authentication

Every endpoint except `/auth/google/login`, `/auth/google/callback`, and
the `/health/*` probes requires an authenticated session:

1. Redirect the user to `GET /auth/google/login`, which redirects to
   Google's consent screen.
2. Google redirects back to `GET /auth/google/callback`, which completes
   the OAuth exchange and sets an `httponly` session cookie (`aeea_session`)
   plus a JS-readable CSRF cookie (`aeea_csrf_token`).
3. Every subsequent request must send the session cookie (the browser does
   this automatically) and, for any state-changing request (`POST`,
   `PUT`, `PATCH`, `DELETE`), must also echo the CSRF cookie's value back
   as an `X-CSRF-Token` header (the double-submit-cookie pattern) --
   `GET`/`HEAD`/`OPTIONS` requests are exempt.

A request with a missing/invalid session returns `401 unauthorized`; a
missing/mismatched CSRF header on a mutating request returns
`403 csrf_check_failed`.

## Errors

Every error response is [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)
`application/problem+json`:

```json
{
  "title": "Not Found",
  "status": 404,
  "code": "not_found",
  "detail": "The requested resource was not found.",
  "request_id": "b1e2...",
  "errors": null
}
```

`code` is the stable, machine-readable identifier to branch on in client
code (`title`/`detail` are human-readable and may change). Common codes:

| `code` | HTTP status | Meaning |
|---|---|---|
| `unauthorized` | 401 | No/invalid session. |
| `csrf_check_failed` | 403 | Missing/mismatched `X-CSRF-Token` on a mutating request. |
| `forbidden` | 403 | Authenticated, but not permitted. |
| `not_found` | 404 | Resource doesn't exist, or isn't owned by the current user. |
| `conflict` | 409 | The request conflicts with current resource state. |
| `validation_error` | 422 | Request body/query parameters failed validation. |
| `rate_limit_exceeded` | 429 | Too many requests -- see the `Retry-After` header. |
| `reauthentication_required` | 401 | Google credential expired; sign in again. |
| `upstream_error` | 502 | Google's API returned an unexpected error. |
| `service_unavailable` | 503 | A required downstream dependency is unavailable. |
| `internal_error` | 500 | An unexpected server-side failure. |

Every response also carries an `X-Request-ID` header (echoed as
`request_id` in error bodies) for correlating a client-reported issue with
server logs.

## Rate limiting

Requests are rate-limited per session (or per client IP if unauthenticated)
on a fixed window. A `429` response includes a `Retry-After` header with
the number of seconds to wait. `/health/*` and `/metrics` are exempt.

## Pagination

List endpoints that support pagination accept `limit`/`offset` query
parameters and return a plain JSON array (not an envelope) -- check each
endpoint's documented default/maximum `limit`.
"""

OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": "Google OAuth sign-in/sign-out and the current session.",
    },
    {
        "name": "dashboard",
        "description": "The daily-briefing summary shown on the home screen.",
    },
    {
        "name": "emails",
        "description": "Inbox listing, urgent/deadline views, read/star toggling.",
    },
    {
        "name": "tasks",
        "description": "Tasks extracted from emails by the AI triage pipeline.",
    },
    {
        "name": "calendar-events",
        "description": "Calendar events extracted from emails and synced to Google.",
    },
    {
        "name": "draft-replies",
        "description": (
            "AI-drafted email replies: list, edit, approve, discard, regenerate. "
            "Never sent automatically -- always requires human approval."
        ),
    },
    {
        "name": "notifications",
        "description": "In-app notifications from reminders, digests, and rules.",
    },
    {
        "name": "notification-rules",
        "description": "User-defined rules for which events send a notification.",
    },
    {
        "name": "notification-channels",
        "description": (
            "External delivery channels (Slack, Discord, Telegram, WhatsApp, "
            "email, webhook) for notifications."
        ),
    },
    {
        "name": "push-devices",
        "description": "Registered desktop (Web Push) and mobile (FCM) push devices.",
    },
    {
        "name": "quiet-hours",
        "description": "Per-user do-not-disturb window for non-urgent notifications.",
    },
    {
        "name": "preferences",
        "description": "Free-form key/value user preferences.",
    },
    {
        "name": "analytics",
        "description": "Email/task/response-time analytics widgets and export reports.",
    },
    {
        "name": "gmail",
        "description": "Gmail labels and account-level Gmail metadata.",
    },
    {
        "name": "system",
        "description": (
            "Operator-facing endpoints: Prometheus metrics (`/metrics`) and "
            "failed-job/dead-letter-queue inspection. Unauthenticated, like `health`."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/readiness probes -- unauthenticated.",
    },
]
