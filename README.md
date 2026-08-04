# AI Executive Email Assistant (AEEA)

[![CI](https://github.com/akshithm05/executive-mail-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/akshithm05/executive-mail-agent/actions/workflows/ci.yml)

An AI-powered executive assistant that connects to Gmail, triages incoming
mail with an LLM pipeline (categorize, prioritize, extract deadlines/tasks,
draft replies, suggest calendar events), and surfaces all of it in a
dashboard — with every AI-drafted reply requiring human approval before it's
ever sent.

## Monorepo layout

| Path | What it is |
|---|---|
| [`backend/`](backend/) | FastAPI application — REST API, LangGraph/Claude AI agent, Postgres + Redis. See [`backend/README.md`](backend/README.md). |
| [`frontend/`](frontend/) | Next.js 16 / React 19 dashboard. See [`frontend/README.md`](frontend/README.md). |
| [`infra/`](infra/) | Docker Compose stack: Postgres, Redis, migrations, API, Prometheus, Grafana. |
| [`docs/`](docs/) | Architecture, deployment, developer, and user documentation (see below). |

## Documentation

| Document | For |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system is designed and why — start here to understand the codebase. |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Configuration reference and how to run this in production. |
| [`docs/deploy/aws.md`](docs/deploy/aws.md), [`gcp.md`](docs/deploy/gcp.md), [`azure.md`](docs/deploy/azure.md), [`digitalocean.md`](docs/deploy/digitalocean.md) | Platform-specific deployment steps. |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Local setup, project layout, testing philosophy, how to add a feature. |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | How to actually use the app once it's running. |
| [`AI_Executive_Email_Assistant_SDD.md`](AI_Executive_Email_Assistant_SDD.md) | The original pre-implementation design document — historical reference; several decisions changed during implementation (see `ARCHITECTURE.md`'s intro for the specific deltas). |

## Quick start

```bash
cd infra
cp ../backend/.env.example ../backend/.env   # then fill in Google OAuth + Anthropic keys
docker compose up --build
```

- API: `http://localhost:8000` (`/docs` for interactive Swagger UI)
- Grafana: `http://localhost:3001` (default `admin`/`admin`)
- Prometheus: `http://localhost:9090`

Then, separately, run the frontend:

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000
```

See [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) for running either
half without Docker, running the test suites, and the code-quality gates.

## What's implemented

- **Google OAuth 2.0 + Gmail integration** — least-privilege scopes
  (`gmail.readonly`/`gmail.labels`, never `gmail.send`), transparent token
  refresh, encrypted token storage.
- **AI email-triage pipeline** (LangGraph + Anthropic Claude, 13-node graph):
  categorization, priority scoring, deadline detection, task extraction,
  tone-aware draft replies (never auto-sent), calendar-event suggestions.
- **Long-term memory** with local deterministic embeddings, importance decay,
  and periodic AI-driven consolidation.
- **Semantic email search**.
- **Notifications** across in-app, Slack, Discord, Telegram, WhatsApp,
  email, generic webhook, and desktop/mobile push, with per-user rules and
  quiet hours.
- **Analytics dashboard**: volume trends, category/priority distribution,
  response-time metrics, CSV/PDF export.
- **Production hardening**: Redis-backed caching + rate limiting, CSRF
  protection, security headers, RFC 9457 structured errors, Sentry +
  OpenTelemetry (both opt-in), Prometheus metrics + a bundled Grafana
  dashboard, a Redis-elected scheduler leader for safe horizontal scaling,
  and a production-safety startup validator that refuses to boot with
  insecure defaults.
- **Test coverage**: backend unit/integration tests (real fake doubles for
  every third-party service, not mocks — see `docs/DEVELOPER_GUIDE.md` §5),
  a frontend Vitest/RTL suite, load tests (Locust), and a CI job that boots
  the real Docker Compose stack to catch anything the hermetic suite can't.

## License

Proprietary — see [`backend/pyproject.toml`](backend/pyproject.toml).
