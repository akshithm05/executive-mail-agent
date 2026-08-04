# Deploying to DigitalOcean (App Platform)

Assumes you've read [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — this covers only
what's DigitalOcean-specific. Target topology: App Platform for the API
(plus a pre-deploy job for migrations) and the frontend, Managed PostgreSQL,
Managed Redis (Valkey) — App Platform's simplicity means most of this is one
declarative spec rather than a sequence of imperative commands.

## 1. Prerequisites

```bash
brew install doctl   # or see doctl's install docs for your platform
doctl auth init
```

## 2. Provision data stores

```bash
doctl databases create aeea-postgres --engine pg --version 16 \
  --region nyc1 --size db-s-1vcpu-1gb --num-nodes 1

# Optional but recommended for >1 instance -- see ../DEPLOYMENT.md §6: it
# backs the scheduler leader election.
doctl databases create aeea-redis --engine valkey --version 7 \
  --region nyc1 --size db-s-1vcpu-1gb --num-nodes 1
```

Note the connection details App Platform needs (`doctl databases connection
aeea-postgres` / `aeea-redis`) — App Platform can also bind a database it
provisions directly into the app spec below, which auto-injects the
connection env vars.

## 3. App spec

App Platform deploys straight from your GitHub repo (build + deploy on
push) rather than a pre-built image, using each component's Dockerfile.
Save this as `.do/app.yaml` at the repo root:

```yaml
name: aeea
region: nyc
services:
  - name: api
    dockerfile_path: backend/Dockerfile
    source_dir: backend
    github:
      repo: <your-org>/executive-mail-agent
      branch: main
      deploy_on_push: true
    http_port: 8000
    instance_count: 2
    instance_size_slug: apps-s-1vcpu-1gb
    health_check:
      http_path: /api/v1/health/ready
      initial_delay_seconds: 15
    envs:
      - key: ENVIRONMENT
        value: production
      - key: DB_HOST
        value: ${aeea-postgres.HOSTNAME}
      - key: DB_PORT
        value: ${aeea-postgres.PORT}
      - key: DB_USER
        value: ${aeea-postgres.USERNAME}
      - key: DB_PASSWORD
        value: ${aeea-postgres.PASSWORD}
        type: SECRET
      - key: DB_NAME
        value: ${aeea-postgres.DATABASE}
      - key: REDIS_HOST
        value: ${aeea-redis.HOSTNAME}
      - key: REDIS_PORT
        value: ${aeea-redis.PORT}
      - key: REDIS_PASSWORD
        value: ${aeea-redis.PASSWORD}
        type: SECRET
      - key: SESSION_COOKIE_SECURE
        value: "true"
      - key: CORS_ORIGINS
        value: https://your-frontend-domain.example
      - key: SECURITY_TOKEN_ENCRYPTION_KEY
        type: SECRET
        value: <generate-with-fernet-and-paste-here-or-set-via-doctl>
      - key: GOOGLE_OAUTH_CLIENT_ID
        value: <client-id>
      - key: GOOGLE_OAUTH_CLIENT_SECRET
        type: SECRET
        value: <client-secret>
      - key: GOOGLE_OAUTH_REDIRECT_URI
        value: https://api.your-domain.example/api/v1/auth/google/callback
      - key: AI_ANTHROPIC_API_KEY
        type: SECRET
        value: <api-key>
  - name: frontend
    dockerfile_path: frontend/Dockerfile
    source_dir: frontend
    github:
      repo: <your-org>/executive-mail-agent
      branch: main
      deploy_on_push: true
    http_port: 3000
    instance_count: 1
    instance_size_slug: apps-s-1vcpu-1gb
    envs:
      - key: NEXT_PUBLIC_API_BASE_URL
        value: https://api.your-domain.example/api/v1
jobs:
  - name: migrate
    dockerfile_path: backend/Dockerfile
    source_dir: backend
    github:
      repo: <your-org>/executive-mail-agent
      branch: main
    kind: PRE_DEPLOY
    run_command: alembic upgrade head
    envs:
      - key: DB_HOST
        value: ${aeea-postgres.HOSTNAME}
      - key: DB_PORT
        value: ${aeea-postgres.PORT}
      - key: DB_USER
        value: ${aeea-postgres.USERNAME}
      - key: DB_PASSWORD
        value: ${aeea-postgres.PASSWORD}
        type: SECRET
      - key: DB_NAME
        value: ${aeea-postgres.DATABASE}
databases:
  - name: aeea-postgres
    engine: PG
    production: true
  - name: aeea-redis
    engine: VALKEY
    production: true
```

`kind: PRE_DEPLOY` is the key piece here — App Platform runs that job to
completion **before** routing traffic to the new `api` deployment, giving
the same "migrate, then serve" ordering as every other platform guide in
this directory, without you needing to sequence it by hand.

## 4. Deploy

```bash
doctl apps create --spec .do/app.yaml
# subsequent deploys, after editing app.yaml or pushing to main:
doctl apps update <app-id> --spec .do/app.yaml
```

`instance_count: 2` on the `api` service is exactly the scaling story from
[`../DEPLOYMENT.md` §6](../DEPLOYMENT.md#6-scaling) — both replicas run the
scheduler, only one (Redis-elected) fires jobs; the Managed Redis
(`aeea-redis`) above is what makes that safe. Scale further by raising
`instance_count` (or switching to autoscaling — see App Platform's
`autoscaling` spec key).

## 5. Secrets

Values marked `type: SECRET` in the spec above are encrypted at rest by App
Platform and never shown again in `doctl apps spec get` after the first
deploy — set them once via the spec (or `doctl apps update` with a fresh
spec file), not via plain `envs` entries.

## 6. CI/CD

App Platform's `deploy_on_push: true` already gives you continuous
deployment from `main` — there's no extra GitHub Actions job needed for the
deploy step itself. Keep `.github/workflows/ci.yml`'s lint/typecheck/test
jobs as the required status checks gating merges to `main`, so nothing
red reaches the branch App Platform deploys from.
