# AI Executive Email Assistant — Backend (Phase 1)

Production-grade backend **foundation** for the AI Executive Email Assistant.
This phase delivers the application skeleton: configuration, logging, database,
migrations, dependency injection, middleware, error handling, health/version
endpoints, containerization, and tests. **Gmail and AI are intentionally not
implemented yet** — OAuth is configured but the flow itself lands in a later
phase.

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
```

Cross-cutting concerns — settings, logging, middleware, error handling — sit
around this core. The composition root is `app/main.py::create_app`, which
wires everything and manages the database lifecycle via an ASGI lifespan.

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
│   ├── main.py                 # App factory + lifespan (DB connect/dispose)
│   ├── config/                 # settings.py, logging.py
│   ├── core/                   # exceptions.py, oauth.py (config only)
│   ├── api/
│   │   ├── deps.py             # DI providers (settings, session, repositories)
│   │   ├── errors.py           # RFC 9457 problem+json handlers
│   │   ├── middleware/         # request-id + access logging, contextvars
│   │   └── v1/                 # router.py + routes/ (health, version)
│   ├── schemas/                # Pydantic response contracts
│   └── infra/
│       ├── db/                 # base.py, mixins.py, session.py (Database)
│       ├── models/             # ORM models (tenant.py) + registry
│       └── repositories/       # base.py (generic) + tenant.py
├── migrations/                 # Alembic env + versions/0001_initial.py
├── tests/                      # unit/ + integration/
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
| `GOOGLE_OAUTH_CLIENT_ID` / `..._SECRET` | empty | Configured now, used later |

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

OpenAPI JSON: `GET /api/v1/openapi.json`. This is the contract the frontend
generates its types from.

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

**Current status:** 19 tests passing; Ruff and Ruff-format clean; OpenAPI and
the initial migration verified to generate correctly.

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

Phase 1 is the foundation only. Subsequent phases build on these seams:

1. **Auth & OAuth flow** — implement the Google consent exchange, encrypted
   token storage, and user/session models.
2. **Gmail integration** — watch/history sync, ingestion, MIME parsing.
3. **Domain services & LangGraph** — triage, drafting, memory.
4. **Scheduler & workers** — APScheduler jobs and async consumers.

The module boundaries here are drawn so each of the above slots in without
reworking the foundation.
