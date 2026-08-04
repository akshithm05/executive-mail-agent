# AI Executive Email Assistant — Backend

FastAPI backend for the AI Executive Email Assistant: Google OAuth/Gmail
integration, a LangGraph + Anthropic Claude email-triage AI pipeline, task/
calendar/draft-reply management, multi-channel notifications, analytics, and
production-grade hardening (Redis caching/rate limiting, CSRF, security
headers, Sentry/OpenTelemetry, Prometheus/Grafana).

For the full picture, see the repo root's [`docs/`](../docs/):

- [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — system design, the AI
  pipeline, data model, security model.
- [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) — configuration reference and
  production deployment (plus platform-specific guides in `docs/deploy/`).
- [`docs/DEVELOPER_GUIDE.md`](../docs/DEVELOPER_GUIDE.md) — local setup,
  testing, how to add a feature.

This file is a quick-reference for working in `backend/` specifically.

## Tech stack

| Concern | Choice |
|---|---|
| Web framework | FastAPI (async) |
| AI orchestration | LangGraph + Anthropic Claude |
| Validation / settings | Pydantic v2 + pydantic-settings |
| ORM | SQLAlchemy 2.0 (async, `asyncpg`) |
| Migrations | Alembic (async env) |
| Database | PostgreSQL 16 |
| Cache / rate limit / scheduler lock | Redis |
| Background jobs | APScheduler (in-process, Redis-leader-elected) |
| Logging | structlog (JSON in prod, console in dev) |
| Observability | Prometheus metrics, Sentry (opt-in), OpenTelemetry (opt-in) |
| Packaging | Docker (multi-stage) + Docker Compose |
| Tests | pytest, pytest-asyncio, httpx, real fake doubles (no `unittest.mock` of internals) |
| Lint/format/type | Ruff, mypy (strict) |

## Project layout

```
backend/
├── app/
│   ├── main.py              # App factory + lifespan (composition root)
│   ├── config/               # settings.py (all env-driven config), logging.py
│   ├── core/                 # exceptions.py, oauth.py, crypto.py (Fernet), time.py
│   ├── api/
│   │   ├── deps.py           # Every DI provider
│   │   ├── errors.py          # RFC 9457 problem+json handlers
│   │   ├── middleware/        # CSRF, rate limit, security headers, request logging
│   │   ├── cache_utils.py     # Cache-or-compute helper for read endpoints
│   │   └── v1/routes/         # One module per resource
│   ├── agents/                # LangGraph triage graph, prompts, embeddings, Claude client
│   ├── schemas/                # Pydantic request/response models
│   ├── services/               # Business logic / orchestration
│   ├── scheduler.py            # Every background job + APScheduler wiring
│   ├── observability.py        # Sentry + OpenTelemetry (both opt-in)
│   ├── openapi_metadata.py     # Swagger UI description + tag ordering
│   └── infra/
│       ├── db/, models/, repositories/    # Persistence
│       ├── google/                        # Gmail/Calendar/OAuth clients, retry/backoff
│       ├── cache.py, leader_lock.py, metrics.py, queue.py, events.py
│       └── ...
├── migrations/                # Alembic env + versions/
├── tests/
│   ├── unit/, integration/     # pytest — see tests/conftest.py + fake_google/fake_anthropic/fake_redis
│   └── load/                   # Locust
├── Dockerfile
├── pyproject.toml             # Ruff / mypy / pytest config
├── requirements.txt / requirements-dev.txt
├── Makefile
└── .env.example                # The authoritative list of every setting
```

## Quick start (Docker)

```bash
# From the repository root:
cp backend/.env.example backend/.env
docker compose -f infra/docker-compose.yml up --build
```

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

Interactive docs: <http://localhost:8000/docs> (Swagger UI) or `/redoc`.

## Local development (no Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
make install                 # pip install -r requirements-dev.txt
cp .env.example .env         # then edit DB_HOST=localhost etc.
make migrate                 # alembic upgrade head
uvicorn app.main:app --reload
```

`make lint` / `make format` / `make typecheck` / `make test` /
`make revision msg="..."` — see [`docs/DEVELOPER_GUIDE.md`](../docs/DEVELOPER_GUIDE.md)
for the full workflow, including running the frontend alongside this and the
Docker-based Postgres/Redis smoke test.

## Configuration

Every setting is environment-driven and validated at startup
(`app/config/settings.py`) — nothing reads `os.environ` directly, and
nothing is undocumented: **`.env.example`** is the authoritative,
fully-commented list of every variable, grouped by concern (`DB_*`,
`GOOGLE_OAUTH_*`, `AI_*`, `REDIS_*`, `SESSION_*`, `SENTRY_*`, `OTEL_*`,
notification-channel settings, and more). See
[`docs/DEPLOYMENT.md` §2](../docs/DEPLOYMENT.md#2-required-configuration)
for which of them are actually required in production, and what happens if
you try to boot with `ENVIRONMENT=production` and an insecure default still
in place (the app refuses to start).

## API endpoints

Every route lives under `API_V1_PREFIX` (default `/api/v1`) and is grouped
by tag in the interactive docs at `/docs` — that's the authoritative,
always-current endpoint reference (auto-generated from the code, so it can't
drift the way a hand-maintained table in this file would). At a glance, the
resource groups are: `auth`, `dashboard`, `emails`, `tasks`,
`calendar-events`, `draft-replies`, `notifications`,
`notification-rules`, `notification-channels`, `push-devices`,
`quiet-hours`, `preferences`, `analytics`, `gmail`, `system`, `health`.

## Testing

```bash
make test                                          # pytest
pytest --cov=app --cov-report=term-missing         # with coverage
```

Every test runs against an isolated, file-backed SQLite database — fast and
hermetic, no external Postgres/Redis required — with real in-process fake
doubles for Google, Anthropic, and Redis (`tests/fake_google/`,
`tests/fake_anthropic/`, `tests/fake_redis.py`) instead of mocking this
codebase's own internals. A separate CI job boots the real Docker Compose
stack (real Postgres, real Redis) specifically to catch anything the
SQLite-backed suite structurally cannot see. See
[`docs/DEVELOPER_GUIDE.md` §5](../docs/DEVELOPER_GUIDE.md#5-test-philosophy--read-this-before-adding-a-mock)
for the full testing philosophy, and `tests/load/README.md` for load
testing.

## Design principles

- **Repository pattern** — persistence is hidden behind a narrow typed
  interface; services never write raw SQL.
- **Dependency injection** — all wiring flows through `app/api/deps.py`;
  `Database`/`Settings`/`Redis` live on `app.state`, not as globals, so
  tests inject freely.
- **Fail open where safety allows, fail closed where it doesn't** — Redis
  outages degrade caching/rate-limiting to "off" rather than erroring; a
  production boot with an insecure default is refused outright. See
  [`docs/ARCHITECTURE.md` §2](../docs/ARCHITECTURE.md#2-key-architectural-decisions).
- **Async-first** throughout: engine, sessions, endpoints, migration env,
  scheduler, AI pipeline.
- **Type hints & docstrings everywhere**, enforced by Ruff (`D`, `N`, `S`,
  `ASYNC`, `B`, ...) and mypy `strict`.
