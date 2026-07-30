# AI Executive Email Assistant — Backend (Phase 1 + 2)

Production-grade backend for the AI Executive Email Assistant.

- **Phase 1** delivered the application skeleton: configuration, logging,
  database, migrations, dependency injection, middleware, error handling,
  health/version endpoints, containerization, and tests.
- **Phase 2** (this update) implements Google sign-in and Gmail read access:
  the full OAuth 2.0 authorization-code flow, encrypted token storage,
  transparent access-token refresh with reauthentication detection, and a
  Gmail API client (profile, labels, read/search messages, attachments) with
  retries, backoff, and client-side rate limiting.

**AI/triage/drafting is intentionally not implemented yet** — that is a later
phase built on top of this Gmail seam.

---

## Table of contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Quick start (Docker)](#quick-start-docker)
- [Local development (no Docker)](#local-development-no-docker)
- [Configuration](#configuration)
- [Database & migrations](#database--migrations)
- [API endpoints](#api-endpoints)
- [Google authentication & Gmail](#google-authentication--gmail)
- [Observability](#observability)
- [Error model](#error-model)
- [Testing & quality gates](#testing--quality-gates)
- [Design principles](#design-principles)
- [What's next](#whats-next)

---

## Architecture

The backend is a **modular monolith** organized with clean-architecture
boundaries:

```
HTTP (FastAPI routes)
   │  depends on
   ▼
Dependency Injection (app/api/deps.py)
   │  provides
   ▼
Repositories (app/infra/repositories)  ──►  ORM models (app/infra/models)
   │                                              │
   └──────────────►  Database (async engine/session, app/infra/db)

app/services/google_auth_service.py       # login/logout/refresh orchestration
   │  depends on
   ▼
app/infra/google/{oauth_client,gmail_client}.py  ──►  Google's HTTP APIs
   │  encrypts/decrypts via
   ▼
app/core/crypto.py (Fernet)  ──►  google_credentials table (ciphertext only)
```

Cross-cutting concerns — settings, logging, middleware, error handling — sit
around this core. The composition root is `app/main.py::create_app`, which
wires everything and manages the database and shared HTTP client lifecycle via
an ASGI lifespan.

## Tech stack

| Concern | Choice |
|---|---|
| Web framework | FastAPI (async) |
| Validation / settings | Pydantic v2 + pydantic-settings |
| ORM | SQLAlchemy 2.0 (async, `asyncpg`) |
| Migrations | Alembic (async env) |
| Database | PostgreSQL 16 |
| Logging | structlog (JSON in prod, console in dev) |
| Packaging | Docker (multi-stage) + Docker Compose |
| Tests | pytest, pytest-asyncio, httpx |
| Lint/format/type | Ruff, mypy |

## Project layout

```
backend/
├── app/
│   ├── main.py                 # App factory + lifespan (DB + HTTP client)
│   ├── config/                 # settings.py, logging.py
│   ├── core/                   # exceptions.py, oauth.py, crypto.py (Fernet)
│   ├── api/
│   │   ├── deps.py             # DI providers (settings, session, repos, auth, gmail)
│   │   ├── errors.py           # RFC 9457 problem+json handlers
│   │   ├── middleware/         # request-id + access logging, contextvars
│   │   └── v1/                 # router.py + routes/ (health, version, auth, gmail)
│   ├── schemas/                # Pydantic response contracts
│   ├── services/
│   │   └── google_auth_service.py  # login/logout/refresh orchestration
│   └── infra/
│       ├── db/                 # base.py, mixins.py, session.py (Database)
│       ├── models/             # tenant, user, google_credential, session
│       ├── repositories/       # base (generic) + tenant/user/credential/session
│       └── google/             # oauth_client, gmail_client, mime_parser,
│                                # http (retry/backoff), rate_limiter, types
├── migrations/                 # Alembic env + versions/ (0001, 0002)
├── tests/                      # unit/ + integration/ + fake_google (test double)
├── Dockerfile
├── alembic.ini
├── pyproject.toml              # Ruff / mypy / pytest config
├── requirements.txt            # runtime deps
├── requirements-dev.txt        # dev/test deps
├── Makefile
└── .env.example
infra/
└── docker-compose.yml          # postgres + migrate + api
```

## Quick start (Docker)

Requires Docker with Compose v2.

```bash
# From the repository root:
cp backend/.env.example backend/.env      # optional; compose reads .env.example directly
docker compose -f infra/docker-compose.yml up --build
```

This starts PostgreSQL, runs migrations once (the `migrate` service), then
serves the API. Verify:

```bash
curl http://localhost:8000/api/v1/health/live     # {"status":"ok"}
curl http://localhost:8000/api/v1/health/ready     # {"status":"ok","checks":{"database":"up"}}
curl http://localhost:8000/api/v1/version
```

Interactive docs: <http://localhost:8000/docs>.

## Local development (no Docker)

Requires Python 3.12+ and a reachable PostgreSQL (or use the compose `db` only).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
make install                 # pip install -r requirements-dev.txt
cp .env.example .env         # then edit DB_HOST=localhost etc.

make migrate                 # alembic upgrade head
uvicorn app.main:app --reload
```

Handy targets: `make lint`, `make format`, `make typecheck`, `make test`,
`make revision msg="add users table"`.

## Configuration

All configuration is environment-driven and validated at startup by
`app/config/settings.py`. Nothing reads `os.environ` directly. Nested groups
use prefixes: `DB_*` for the database and `GOOGLE_OAUTH_*` for OAuth. See
`.env.example` for the full list. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `local` | `local` / `test` / `staging` / `production` |
| `LOG_LEVEL` | `INFO` | Minimum log level |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | — | PostgreSQL connection |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `GOOGLE_OAUTH_CLIENT_ID` / `..._SECRET` | empty | Google Cloud OAuth 2.0 Web client |
| `GOOGLE_OAUTH_REDIRECT_URI` | `.../auth/google/callback` | Must match the client's registered redirect URI |
| `GOOGLE_OAUTH_SCOPES` | `openid,email,profile,gmail.readonly,gmail.labels` | Comma-separated OAuth scopes |
| `GMAIL_REQUESTS_PER_SECOND` / `GMAIL_BURST_CAPACITY` | `5` / `10` | Client-side token-bucket rate limit |
| `GMAIL_MAX_RETRIES` | `5` | Retry attempts for 429/5xx Gmail responses |
| `SECURITY_TOKEN_ENCRYPTION_KEY` | dev-only default | Fernet key encrypting tokens at rest — **override in every real deployment** |
| `SESSION_COOKIE_SECURE` | `true` | `false` for local http development only |
| `SESSION_POST_LOGIN_REDIRECT_URL` | empty | Frontend URL to redirect to after login; empty returns JSON instead |

## Database & migrations

- Models inherit a shared declarative `Base` with a deterministic constraint
  naming convention, so Alembic diffs stay stable and reviewable.
- The async Alembic environment (`migrations/env.py`) pulls its URL from the
  same settings the app uses — one source of truth.
- Generate a migration after changing models:

  ```bash
  make revision msg="describe change"   # autogenerate
  make migrate                          # apply
  ```

- Render SQL without a database (useful in review/CI):

  ```bash
  alembic upgrade head --sql
  ```

## API endpoints

All endpoints are mounted under `API_V1_PREFIX` (default `/api/v1`).

| Method | Path | Description |
|---|---|---|
| GET | `/health/live` | Liveness — process can serve HTTP (no dependencies) |
| GET | `/health/ready` | Readiness — checks the database; `503` when degraded |
| GET | `/version` | App name, semantic version, environment, git SHA |
| GET | `/auth/google/login` | Redirect to Google's OAuth consent screen |
| GET | `/auth/google/callback` | Google redirects here; completes login, sets session cookie |
| GET | `/auth/me` | The signed-in user's own profile |
| POST | `/auth/refresh` | Force-refresh the Google access token |
| POST | `/auth/logout` | Revoke the session and (best-effort) the Google grant |
| GET | `/gmail/profile` | Mailbox profile: address, message/thread counts |
| GET | `/gmail/labels` | List all labels |
| POST | `/gmail/labels` | Create a label (`409` if the name already exists) |
| GET | `/gmail/messages` | Search/list messages — `q`, `pageToken`, `maxResults` |
| GET | `/gmail/messages/{id}` | Read one message: headers, text/HTML body, attachment metadata |
| GET | `/gmail/messages/{id}/attachments/{attachmentId}` | Read one attachment (base64 in JSON) |

`/gmail/*` and `/auth/me`, `/auth/refresh`, `/auth/logout` all require the
first-party session cookie (see below) and return `401` with
`code: "unauthorized"` if it is missing/expired, or `code:
"reauthentication_required"` if Google rejected the stored refresh token.

OpenAPI JSON: `GET /api/v1/openapi.json`. This is the contract the frontend
generates its types from.

## Google authentication & Gmail

### Setup (one-time, per Google Cloud project)

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the
   **Gmail API** for your project.
2. Create an **OAuth 2.0 Client ID** (Application type: *Web application*).
   Add `http://localhost:8000/api/v1/auth/google/callback` (or your deployed
   URL) to **Authorized redirect URIs**.
3. Copy the client id/secret into `GOOGLE_OAUTH_CLIENT_ID` /
   `GOOGLE_OAUTH_CLIENT_SECRET` in `.env`.
4. Generate a real encryption key and set `SECURITY_TOKEN_ENCRYPTION_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
5. If your app is in "Testing" publishing status in the OAuth consent
   screen, add your Google account as a test user, or publish the app.

### Login flow

1. Browser navigates to `GET /api/v1/auth/google/login`. The server generates
   a random `state` (stored in a short-lived `httpOnly` cookie) and 302s to
   Google's consent screen with `access_type=offline&prompt=consent` (so a
   refresh token is always granted, even on repeat logins).
2. The user consents; Google redirects to `GET /api/v1/auth/google/callback`
   with `code` and `state`.
3. The server verifies `state` against the cookie (CSRF protection),
   exchanges `code` for tokens, fetches the Google identity (`sub`, `email`,
   `name`, `picture`), and **encrypts and stores** the access/refresh tokens
   (`google_credentials` table). A personal `Tenant` + `User` row is
   auto-provisioned on first login.
4. A first-party session is created (`sessions` table: a SHA-256 hash of a
   random 32-byte token) and set as an `httpOnly`, `Secure`, `SameSite=Lax`
   cookie. If `SESSION_POST_LOGIN_REDIRECT_URL` is set, the browser is
   redirected there; otherwise the callback returns the user's profile as
   JSON (useful for testing the API directly, with no frontend).

### Token lifecycle

- **Encryption at rest**: both the access and refresh token are encrypted
  with Fernet (`app/core/crypto.py`) before being written to Postgres. A
  database dump alone does not expose mailbox access.
- **Transparent refresh**: `GmailClientDep` (the DI provider every `/gmail/*`
  route depends on) calls `GoogleAuthService.get_valid_access_token`, which
  refreshes the access token automatically whenever fewer than 120 seconds
  remain on it — callers never see an expired-token error from Gmail.
- **Reauthentication**: if Google rejects a refresh (`invalid_grant` — the
  user revoked access, changed their password, etc.), the credential is
  flagged `needs_reauth` and every subsequent call raises
  `ReauthenticationRequiredError` (`401`,
  `code: "reauthentication_required"`) until the user repeats the login flow.
- **Logout**: revokes the session locally (so the cookie is immediately
  useless even if not cleared client-side) and best-effort calls Google's
  `/revoke` endpoint; a Google outage never blocks logout.

### Resilience: retries and rate limiting

- `app/infra/google/http.py` retries connection errors, timeouts, and
  `429`/`5xx` responses with exponential backoff + jitter (`tenacity`),
  honoring the server's `Retry-After` header verbatim when present instead of
  guessing. Retries exhausted → `RateLimitExceededError` (`429`) or
  `UpstreamServiceError` (`502`), never a raw `httpx` exception.
- `app/infra/google/rate_limiter.py` is a process-wide async token bucket
  (`GMAIL_REQUESTS_PER_SECOND` / `GMAIL_BURST_CAPACITY`) that every Gmail call
  waits on before sending, smoothing bursts so the process is less likely to
  trigger Google's quota in the first place. It is in-process only — running
  multiple API replicas still relies on honoring Google's own 429s as the
  authoritative limit.

### Reading email

`GET /gmail/messages/{id}` parses Gmail's recursive MIME `payload` tree
(`app/infra/google/mime_parser.py`) into a flat response: decoded
`text_plain` / `text_html` bodies and attachment metadata (filename, MIME
type, size, `attachment_id`) without the attachment bytes. Fetch the bytes
separately via `GET /gmail/messages/{id}/attachments/{attachmentId}` (base64
in the JSON body) — this matches Gmail's own two-call design and avoids
downloading large attachments a caller doesn't need.

## Observability

- **Structured logs** via structlog: JSON in non-local environments, coloured
  console locally.
- **Correlation id**: `RequestLoggingMiddleware` reads `X-Request-ID` (or
  generates one), binds it to the log context and a context variable, echoes it
  on the response, and logs a `request_completed` line with status and latency.
- **Redaction**: a logging processor masks sensitive keys (tokens, passwords,
  cookies) so they never reach the log sink.

## Error model

Every error becomes an RFC 9457 `application/problem+json` response:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "code": "not_found",
  "detail": "The requested resource was not found.",
  "request_id": "0f1a...c9"
}
```

Domain code raises typed exceptions from `app/core/exceptions.py`
(`NotFoundError`, `ConflictError`, `ValidationError`, ...). Unexpected errors
are logged with a stack trace but return only a generic message plus the
correlation id — internals are never leaked.

## Testing & quality gates

```bash
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy (strict)
make test        # pytest
```

Tests run against an isolated, file-backed SQLite database per test — fast and
hermetic, no external Postgres required. Coverage includes settings parsing,
logging/redaction, the OAuth config helper, the health and version endpoints,
the error/correlation-id middleware, and a full repository CRUD roundtrip.

**Current status:** 20 tests passing (Ruff, Ruff-format, and mypy strict
clean); the full stack (`docker compose up`) has been verified end to end —
Postgres starts, Alembic migrates, and `/health/live`, `/health/ready`,
`/version`, and error responses all return correctly against the real
container.

## Design principles

- **Clean architecture / repository pattern** — persistence is hidden behind a
  narrow typed interface; services depend on abstractions.
- **Dependency injection** — all wiring flows through `app/api/deps.py`; the
  `Database` and `Settings` live on `app.state`, not as globals, so tests
  inject freely.
- **SOLID** — single-responsibility modules, open/closed error and repository
  hierarchies, dependency inversion at the DI seam.
- **Async-first** — async engine, sessions, endpoints, and migration env.
- **Type hints & docstrings everywhere**, enforced by Ruff (`D`, `N`, `S`,
  `ASYNC`, ...) and mypy `strict`.

## What's next

Phases 1 and 2 built the foundation and Google/Gmail read access. Subsequent
phases build on these seams:

1. **Gmail sync** — `users.history.list` incremental sync (the `historyId`
   from `/gmail/profile` is the starting point), Pub/Sub push notifications
   (`users.watch`), and persisting ingested messages.
2. **Write actions** — sending/drafting mail, modifying labels on messages
   (currently only label *creation* and message *reading* are implemented).
3. **Domain services & LangGraph** — triage, drafting, memory.
4. **Scheduler & workers** — APScheduler jobs and async consumers.
5. **Distributed rate limiting** — the current Gmail rate limiter is a single
   in-process token bucket; a multi-replica deployment should move it to a
   shared store (e.g. Redis) to enforce one limit across instances.

The module boundaries here are drawn so each of the above slots in without
reworking the foundation.
