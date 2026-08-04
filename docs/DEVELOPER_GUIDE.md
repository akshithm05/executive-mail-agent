# Developer Guide

For system design, read [`ARCHITECTURE.md`](ARCHITECTURE.md) first — this
document is about working *in* the codebase day to day, not how it's shaped.

## 1. Prerequisites

- Docker + Docker Compose (the fastest path to a fully working stack).
- Python 3.12+ and Node.js 22+ if you want to run either half without
  Docker.
- A Google Cloud project with the Gmail API enabled and an OAuth 2.0 client
  (see [`DEPLOYMENT.md` §2](DEPLOYMENT.md#2-required-configuration)) — only
  needed if you want to exercise real Gmail login locally; the test suites
  use an in-process fake Google server and need no real credentials.
- An Anthropic API key (<https://console.anthropic.com/>) — only needed to
  exercise the real AI-triage pipeline; the test suite uses an in-process
  fake Anthropic server.

## 2. Local setup

### 2.1 Full stack via Docker Compose (recommended)

```bash
cd infra
cp ../backend/.env.example ../backend/.env
# fill in GOOGLE_OAUTH_CLIENT_ID/_SECRET and AI_ANTHROPIC_API_KEY if you want
# real Gmail/AI behavior; everything else has a working local default.
docker compose up --build
```

- API: `http://localhost:8000` (`/docs` for Swagger UI, `/redoc` for ReDoc).
- Grafana: `http://localhost:3001` (default `admin`/`admin`).
- Prometheus: `http://localhost:9090`.

### 2.2 Backend without Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
make install                    # pip install -r requirements-dev.txt
cp .env.example .env
# Point DB_HOST at a local/managed Postgres; Redis is optional (fails open).
make migrate                    # alembic upgrade head
uvicorn app.main:app --reload
```

### 2.3 Frontend without Docker

```bash
cd frontend
npm install
# NEXT_PUBLIC_API_BASE_URL defaults to http://localhost:8000/api/v1
npm run dev
```

## 3. Project layout

```
backend/app/
├── main.py                # Composition root: create_app(), lifespan, middleware order
├── config/                # Settings (Pydantic BaseSettings, one class per concern), logging
├── api/
│   ├── deps.py             # Every DI provider (DB session, current user, services, ...)
│   ├── middleware/         # CSRF, rate limit, security headers, request logging
│   ├── errors.py           # RFC 9457 exception handlers
│   ├── cache_utils.py      # Generic cache-or-compute helper for read endpoints
│   └── v1/routes/          # One module per resource; thin — delegate to services
├── agents/                 # LangGraph triage graph, prompts, embeddings, Claude client
├── services/               # Business logic / use-case orchestration
├── infra/
│   ├── db/                 # Engine/session (Database class)
│   ├── models/              # SQLAlchemy ORM models
│   ├── repositories/        # One repository per model; the only layer that writes SQL
│   ├── google/               # Gmail/Calendar/OAuth HTTP clients, retry/backoff, rate limiter
│   ├── cache.py, leader_lock.py, metrics.py, queue.py, events.py
│   └── ...
├── schemas/                # Pydantic request/response models (API-facing shape)
├── scheduler.py            # Every background job + APScheduler wiring
├── observability.py        # Sentry + OpenTelemetry setup (both opt-in, no-op if unconfigured)
└── openapi_metadata.py     # Swagger UI description + tag ordering

backend/tests/
├── unit/                  # No I/O, or a fake double standing in for a third party
├── integration/            # Real (SQLite) DB, real ASGI transport, real fake servers
└── load/                   # Locust — see tests/load/README.md

frontend/src/
├── app/                    # Next.js App Router pages (one per top-level nav item)
├── components/              # dashboard/, shell/, shared/, ui/ (shadcn primitives)
├── lib/                    # api.ts (typed fetch client), auth.tsx, utils.ts, types.ts
└── hooks/                  # useAsync (the one hook every page's data-fetching goes through)
```

## 4. Running the tests

```bash
# Backend
cd backend
make test                       # pytest (SQLite-backed, hermetic, no external services)
pytest --cov=app --cov-report=term-missing   # with coverage (needs pytest-cov)

# Frontend
cd frontend
npm test                        # vitest run
npm run test:watch              # vitest, watch mode

# Load (against a running stack, local or staging)
cd backend
pip install -r tests/load/requirements-load.txt
# see tests/load/README.md for obtaining a session cookie first
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

The backend suite is entirely SQLite-backed and hermetic — no Docker, no
network, no real Postgres needed to run it. A separate CI job
(`docker-smoke-test` in `.github/workflows/ci.yml`) boots the *real*
Docker Compose stack (real Postgres, real Redis) specifically to catch
dialect-specific bugs the SQLite-backed suite structurally cannot see —
run it locally the same way if you're touching anything Postgres-specific
(raw SQL, dialect-specific column types, `ON CONFLICT` clauses):

```bash
cd infra
docker compose up --build -d db redis migrate api
curl http://localhost:8000/api/v1/health/ready
docker compose down -v
```

## 5. Test philosophy — read this before adding a mock

This codebase deliberately avoids `unittest.mock` stubbing of its own
internals. Every third-party service has a **real fake double** it talks to
over a real interface instead:

- `tests/fake_google/` — a real FastAPI app implementing Google's OAuth +
  Gmail + Calendar endpoints, swapped in via `httpx.ASGITransport`. Real
  HTTP request/response cycles, real MIME/base64 parsing on the way out.
- `tests/fake_anthropic/` — same idea for the Claude API, verified against
  the installed SDK's actual wire contract.
- `tests/fake_redis.py` — a real in-memory implementation of the specific
  `redis.asyncio.Redis` surface this codebase actually calls (`get`, `set`
  with real `nx`/`xx`/`ex` semantics, `incr`, `expire`, `ping`), not a mock
  of our own cache-service code.

When you add a new external dependency, follow this pattern: build the
narrowest real fake that satisfies the actual interface, don't stub call
sites inside this codebase. The one accepted exception is monkeypatching a
*true* leaf boundary that has no injectable transport at all (e.g.
`pywebpush.webpush`, which performs a synchronous `requests`-based call with
no async client to swap — see `tests/unit/test_push_senders.py`'s module
docstring for the reasoning).

## 6. Code quality gates

```bash
cd backend
make lint          # ruff check app tests
make format         # ruff format app tests
make typecheck       # mypy app
```

```bash
cd frontend
npm run lint         # eslint
npx tsc --noEmit      # strict type check
```

All four run in CI (`.github/workflows/ci.yml`) on every push/PR, plus the
full test suites and the Docker smoke test. A PR is not mergeable-clean
until all of them pass.

## 7. Common tasks

### 7.1 Adding a new API endpoint

1. Add/extend the Pydantic schema in `app/schemas/<resource>.py`.
2. Add the repository method in `app/infra/repositories/<resource>.py` if
   the query doesn't already exist.
3. Add the service method in `app/services/<resource>.py` (business logic —
   never raw SQL here, that's the repository's job).
4. Add the DI provider in `app/api/deps.py` if the service isn't already
   wired (`Annotated[YourService, Depends(get_your_service)]`).
5. Add the route in `app/api/v1/routes/<resource>.py`: depend on
   `CurrentUserDep` + your service dep, give it a `summary=`, and a
   `response_model=` (or an explicit `responses={...}` if it doesn't return
   the standard shape). Every route is auto-tagged by its router's `tags=`.
6. Write an integration test in `tests/integration/` driving it through a
   real `AsyncClient` (see `tests/conftest.py`'s `client`/`logged_in_client`
   fixtures) — assert status code, response shape, and (for a mutating
   route) that it actually persisted.

### 7.2 Adding a new scheduled job

Add the job function to `app/scheduler.py` (own DB session, own try/except
per unit of work so one bad record doesn't block the batch — see
`dispatch_due_reminders` for the pattern), then register it in
`build_scheduler()` wrapped in `track_job(...)` for metrics, with its
interval sourced from a new `SchedulerSettings` field (never hardcoded).
Write both: a direct unit/integration test of the job function itself
(seed data, call the function, assert the DB state), and confirm
`build_scheduler()`'s job-registration test (`tests/integration/test_scheduler_jobs.py::test_build_scheduler_registers_every_job`)
still passes with your new job id included.

### 7.3 Adding a new notification channel

1. Add a `<Channel>Settings` class to `app/config/settings.py` with an
   `is_configured` computed property.
2. Add a `<Channel>Sender` to `app/services/notifications/` implementing
   `async def send(self, *, title, body, config, ...) -> None`, raising
   `ChannelNotConfiguredError` / `ChannelDeliveryError` /
   `DeviceUnregisteredError` as appropriate (`app/services/notifications/errors.py`).
3. Wire it into `ChannelSenders`/`build_channel_senders` in
   `app/services/notification_dispatch.py`.
4. If it's a "singleton" channel (one destination per user, like Slack), add
   it to `SINGLETON_CHANNEL_TYPES` (`app/infra/models/notification_channel_config.py`);
   if it's multi-device (like push), model it after `PushDevice` instead.
5. Test it the way `tests/unit/test_notification_senders.py` /
   `tests/unit/test_push_senders.py` do: fake the real HTTP boundary via
   `httpx.ASGITransport` where the sender takes an injectable client, or the
   narrowest possible monkeypatch of the true leaf call where it doesn't
   (see §5).

## 8. Known gaps

Found during the Phase 15 code-quality audit, left here rather than fixed
silently since the right resolution (wire up vs. delete) is a product
decision, not a code-cleanliness one:

- **Seven fully-implemented, fully-typed, but unwired modules**:
  `app/schemas/{ai_history,attachment,audit_log,label,memory,prompt_log,summary}.py`
  and `app/services/{ai_history,attachment,audit_log,label,prompt_log,summary}.py`
  (the standalone `memory` schema/service pair — not `app/services/memory.py`,
  which *is* live and heavily used) are complete, correctly-typed
  implementations with no route, no scheduled job, and no other service
  calling them. They appear to be scaffolding from an earlier phase whose
  corresponding feature (audit-trail API, per-email attachment API, AI
  decision-history API, label-management API, prompt-log inspection API,
  digest-history API) was never exposed. Each is either worth a thin route
  module (the repository + service layers already exist and are tested) or
  should be deleted — recommend deciding per-module rather than blanket
  action.
- **`TaskRead.status`/`.priority` are typed `str`, not the `TaskStatus`/
  `TaskPriority` `Literal` types** used on `TaskCreate`/`TaskUpdate`
  (`app/schemas/task.py`) — the response schema loses the enum
  documentation Swagger would otherwise render. Left as-is rather than
  changed opportunistically during the Phase 15c OpenAPI polish pass,
  since narrowing a response type has serialization/validation
  implications worth its own reviewed change, not a drive-by edit.
- **`app/main.py`'s lifespan function is only ~52% line-covered by the unit
  test suite** — not a gap in verification, but a structural limit:
  `DatabaseSettings.async_dsn` is hardcoded to the `postgresql+asyncpg`
  scheme, so the real lifespan cannot run against the hermetic SQLite test
  database. It's fully exercised instead by the `docker-smoke-test` CI job
  and by manual live verification against the real Docker Compose stack —
  see [`ARCHITECTURE.md` §14](ARCHITECTURE.md#14-testing-strategy).
