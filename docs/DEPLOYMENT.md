# Deployment Guide

This is the platform-agnostic deployment reference: what the system needs to
run, how it's configured, and how to run it safely in production. For
platform-specific manifests/steps, see:

- [`docs/deploy/aws.md`](deploy/aws.md) — AWS (ECS Fargate)
- [`docs/deploy/gcp.md`](deploy/gcp.md) — Google Cloud (Cloud Run)
- [`docs/deploy/azure.md`](deploy/azure.md) — Azure (Container Apps)
- [`docs/deploy/digitalocean.md`](deploy/digitalocean.md) — DigitalOcean (App Platform)

All four assume everything in this document as their common baseline.

## 1. What you're deploying

Two independently deployable images, plus managed dependencies:

| Component | Image | Notes |
|---|---|---|
| **API** | `backend/Dockerfile` (target: runtime) | Stateless; horizontally scalable. Also runs the in-process scheduler (leader-elected, see below) — there is no separate worker deployable. |
| **Migrate** | Same image, `alembic upgrade head` entrypoint | Run once per deploy, before the API starts serving the new version. |
| **Frontend** | `frontend/Dockerfile` (Node standalone server) | Talks to the API entirely client-side via `NEXT_PUBLIC_API_BASE_URL` (baked in at build time — see §3). |
| **PostgreSQL** | Managed (RDS / Cloud SQL / Azure Database for PostgreSQL / DigitalOcean Managed DB) or self-hosted | Required. |
| **Redis** | Managed (ElastiCache / Memorystore / Azure Cache for Redis / DigitalOcean Managed Redis) or self-hosted | *Optional but strongly recommended.* Every Redis-backed feature (caching, rate limiting, scheduler leader election) fails open without it — the app still boots and serves traffic, just without those protections, and multi-replica deployments risk duplicate scheduled-job firing (see [Architecture §2](ARCHITECTURE.md#2-key-architectural-decisions)). |
| **Prometheus + Grafana** | `infra/docker-compose.yml` services, or your platform's managed equivalent | Optional; the API exposes `/api/v1/metrics` regardless of what scrapes it. |

## 2. Required configuration

Every setting is an environment variable (`app/config/settings.py`, Pydantic
`BaseSettings`); the full reference list with defaults and comments is
[`backend/.env.example`](../backend/.env.example) — copy it and fill in
the blanks. The settings below are the ones you cannot skip for a real
deployment:

| Variable | Why it's required |
|---|---|
| `ENVIRONMENT=production` | Enables production-only behavior (HSTS, stricter startup validation — see below). |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Postgres connection. |
| `SECURITY_TOKEN_ENCRYPTION_KEY` | Fernet key encrypting Google OAuth tokens and notification-channel secrets at rest. Generate one **per environment**: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Never reuse the repo's dev-only default in production — the app refuses to boot with it (see below). |
| `SESSION_COOKIE_SECURE=true` | Required once you're serving over HTTPS (always, in production). |
| `CORS_ORIGINS` | Must be your real frontend origin(s) — not `*`, not `localhost`. |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` | From Google Cloud Console → APIs & Services → Credentials. The redirect URI must be registered there exactly and must point at your deployed API's `/api/v1/auth/google/callback`. |
| `AI_ANTHROPIC_API_KEY` | From <https://console.anthropic.com/>. The API and ingestion still work without it — queued AI-triage jobs are skipped with a warning log — but that defeats the product's purpose in production. |

Everything else (Redis, Sentry, OpenTelemetry, notification channels,
scheduler cadence, memory tuning) is optional and defaults to a safe
disabled/no-op state.

### 2.1 The production-safety gate

`Settings` has a validator (`_reject_insecure_production_config`) that
**refuses to boot** with `ENVIRONMENT=production` if any of the following is
still true — this is deliberate fail-fast behavior, not a bug to work around:

- `SECURITY_TOKEN_ENCRYPTION_KEY` is still the repo's public dev-only default.
- `SESSION_COOKIE_SECURE` is `false`.
- `CORS_ORIGINS` contains `*` or `http://localhost:3000`.
- Google OAuth isn't configured (`GOOGLE_OAUTH_CLIENT_ID`/`_SECRET` empty).

If the container crash-loops on startup in production, check its logs first
— the raised `ValueError` lists every violation.

## 3. Building the image

```bash
cd backend
docker build -t aeea-backend:latest .
```

Multi-stage build: a `builder` stage installs dependencies into `/install`
with a BuildKit pip cache mount, and the `runtime` stage copies only that
prefix in — no compiler toolchain, no pip cache, in the final image. Runs as
a non-root `app` user. `HEALTHCHECK` is baked in (`curl -f
http://localhost:8000/api/v1/health/live`).

```bash
cd frontend
docker build -t aeea-frontend:latest \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.example/api/v1 .
```

`NEXT_PUBLIC_API_BASE_URL` is a **build-time** argument, not a runtime
environment variable — Next.js inlines `NEXT_PUBLIC_*` values into the
client JS bundle at build time (`next.config.ts` sets
`output: "standalone"`, which is what `Dockerfile` builds against), so it
must be supplied to `docker build`, not just `docker run`. Platforms that
build from source themselves (e.g. DigitalOcean App Platform,
Vercel) instead take it as a regular build-time env var in their own UI —
see `docs/deploy/*.md` for exactly where per platform.

## 4. Running migrations

Alembic manages schema migrations (`backend/migrations/`). Run this **once,
before** the new API version starts serving traffic — every platform guide
in `docs/deploy/` wires this as a pre-deploy/init job, never as part of the
API container's own startup, so a migration failure blocks the deploy
instead of half the fleet booting against a stale schema:

```bash
docker run --rm --env-file .env aeea-backend:latest alembic upgrade head
```

Migrations are written expand/contract-style (see `backend/migrations/versions/`)
so a rolling deploy never has old and new code running against an
incompatible schema simultaneously.

## 5. Health checks

| Endpoint | Purpose | What it checks |
|---|---|---|
| `GET /api/v1/health/live` | Liveness — "is the process up" | Nothing external; always 200 if the process can respond. |
| `GET /api/v1/health/ready` | Readiness — "can it serve real traffic" | Database connectivity (gates the response: 503 if down). Redis is reported informationally in the body but never flips the status, since Redis-backed features fail open. |

Point your load balancer's health check and your orchestrator's
readiness/liveness probes at these two, respectively.

## 6. Scaling

- **API**: stateless, scale horizontally behind a load balancer. Every
  replica runs the in-process APScheduler, but only one — elected via a
  Redis `SET NX EX` lock, renewed every 20s with a 60s TTL
  (`app/infra/leader_lock.py`) — actually fires scheduled jobs. **This means
  Redis is a soft requirement for safe horizontal scaling**: without it, the
  leader lock fails open to *every* replica believing it's the leader,
  and every replica fires every scheduled job (duplicate digests,
  duplicate Gmail polls, etc.) — fine for a single-replica deployment,
  not for N replicas. Run Redis if you're running more than one API
  replica.
- **Database connection pool**: `DB_POOL_SIZE` (default 5) + `DB_MAX_OVERFLOW`
  (default 10) *per replica* — size your Postgres `max_connections` (or
  PgBouncer) accordingly as you scale replica count.
- **Frontend**: stateless, scale horizontally trivially (no session state
  lives there — it's held entirely in the API's session cookie).

## 7. Monitoring

- `GET /api/v1/metrics` — Prometheus text-exposition format. `infra/prometheus/prometheus.yml`
  is a working scrape config (15s interval); adapt the target for your
  platform's service discovery.
- `infra/grafana/dashboards/aeea-overview.json` — a pre-built dashboard
  (HTTP request rate/p95 latency, job outcomes, retry/dead-letter-queue
  depth, cache hit rate, rate-limit rejections, health-check status, AI
  processing queue depth). `infra/grafana/provisioning/` auto-loads it and
  the Prometheus datasource if you run Grafana from the bundled compose
  file; for a managed Grafana, import the dashboard JSON and point it at
  your Prometheus datasource manually.
- **Sentry** (`SENTRY_DSN`) and **OpenTelemetry** (`OTEL_EXPORTER_OTLP_ENDPOINT`)
  are both opt-in — set either to enable it, leave unset to skip it
  entirely. Neither can crash startup even if misconfigured (every setup
  call is defensively wrapped).

## 8. Local reference deployment (Docker Compose)

The fastest way to see every piece running together, and the reference every
cloud-specific guide is checked against:

```bash
cd infra
cp ../backend/.env.example ../backend/.env   # fill in secrets
docker compose up --build
```

Brings up: `db` (Postgres), `redis`, `migrate` (runs once, exits 0), `api`,
`prometheus`, `grafana` (`localhost:3001`, default admin/admin — change it
before exposing this anywhere but localhost). The API is on `localhost:8000`
(`/docs` for Swagger UI). This is **not** a production topology as-is (single
Postgres/Redis instance, no TLS termination, no load balancer) — it's the
fastest path to a fully working local stack, and the basis every
platform-specific guide builds on.

## 9. Secrets management

Never bake secrets into the image or commit them to `.env` in version
control (`.env` is gitignored). In production, inject them via your
platform's secret store, not plain environment variables in a task
definition/manifest where avoidable:

- **AWS**: Secrets Manager or SSM Parameter Store, referenced by ECS task
  definitions.
- **GCP**: Secret Manager, mounted/injected into Cloud Run.
- **Azure**: Key Vault, referenced by Container Apps secret references.
- **DigitalOcean**: App Platform's encrypted environment variables.

See the platform-specific guides in `docs/deploy/` for the exact mechanism
on each.

## 10. Zero-downtime rolling deploys

1. Run the migration job against the new image (expand/contract migrations
   mean the *old* API code keeps working against the post-migration schema).
2. Roll the API replicas one at a time (or in batches), each one passing its
   readiness probe before the next is cycled — standard rolling-update
   behavior on every platform in `docs/deploy/`.
3. The Redis-elected scheduler leader may briefly change hands during a
   rolling deploy (the outgoing leader's lock expires within its 60s TTL if
   it doesn't shut down cleanly first) — at most one scheduled-job cycle is
   delayed by a few seconds, never duplicated (the lock is exclusive).
