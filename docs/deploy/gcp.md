# Deploying to Google Cloud (Cloud Run)

Assumes you've read [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — this covers only
what's GCP-specific. Target topology: Cloud Run for the API, Cloud SQL for
Postgres, Memorystore for Redis, Secret Manager for secrets, Artifact
Registry for images.

## 1. Prerequisites

```bash
gcloud auth login
gcloud config set project <your-project-id>
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  redis.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com vpcaccess.googleapis.com
```

## 2. Push the image to Artifact Registry

```bash
gcloud artifacts repositories create aeea --repository-format=docker \
  --location=us-central1

cd backend
gcloud auth configure-docker us-central1-docker.pkg.dev
docker build -t us-central1-docker.pkg.dev/<project-id>/aeea/backend:latest .
docker push us-central1-docker.pkg.dev/<project-id>/aeea/backend:latest
```

## 3. Provision data stores

```bash
# Postgres (Cloud SQL)
gcloud sql instances create aeea-postgres \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --no-assign-ip \
  --network=default
gcloud sql databases create aeea --instance=aeea-postgres
gcloud sql users set-password postgres --instance=aeea-postgres --password='<db-password>'

# Redis (Memorystore) -- optional but recommended for >1 instance (see
# ../DEPLOYMENT.md §6: it backs the scheduler leader election).
gcloud redis instances create aeea-redis \
  --size=1 --region=us-central1 --tier=basic --redis-version=redis_7_0
```

Cloud Run reaches both via a **Serverless VPC Access connector** (Cloud SQL
can also use the Cloud SQL Auth Proxy sidecar, which Cloud Run supports
natively via `--add-cloudsql-instances`):

```bash
gcloud compute networks vpc-access connectors create aeea-connector \
  --region=us-central1 --network=default --range=10.8.0.0/28
```

## 4. Store secrets

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | gcloud secrets create aeea-token-encryption-key --data-file=-
echo -n '<db-password>' | gcloud secrets create aeea-db-password --data-file=-
echo -n '<client-secret>' | gcloud secrets create aeea-google-oauth-secret --data-file=-
echo -n '<api-key>' | gcloud secrets create aeea-anthropic-key --data-file=-
```

## 5. Run the migration (once, before deploying the service)

Cloud Run Jobs (not the Service) is the right primitive for a one-shot task:

```bash
gcloud run jobs create aeea-migrate \
  --image=us-central1-docker.pkg.dev/<project-id>/aeea/backend:latest \
  --region=us-central1 \
  --set-cloudsql-instances=<project-id>:us-central1:aeea-postgres \
  --vpc-connector=aeea-connector \
  --set-env-vars="DB_HOST=/cloudsql/<project-id>:us-central1:aeea-postgres,DB_NAME=aeea,DB_USER=postgres" \
  --set-secrets="DB_PASSWORD=aeea-db-password:latest" \
  --command="alembic" --args="upgrade,head"

gcloud run jobs execute aeea-migrate --region=us-central1 --wait
```

## 6. Deploy the API service

```bash
gcloud run deploy aeea-backend \
  --image=us-central1-docker.pkg.dev/<project-id>/aeea/backend:latest \
  --region=us-central1 \
  --platform=managed \
  --vpc-connector=aeea-connector \
  --add-cloudsql-instances=<project-id>:us-central1:aeea-postgres \
  --min-instances=1 --max-instances=10 \
  --port=8000 \
  --set-env-vars="ENVIRONMENT=production,DB_HOST=/cloudsql/<project-id>:us-central1:aeea-postgres,DB_NAME=aeea,DB_USER=postgres,REDIS_HOST=<memorystore-ip>,SESSION_COOKIE_SECURE=true,CORS_ORIGINS=https://your-frontend-domain.example,GOOGLE_OAUTH_CLIENT_ID=<client-id>,GOOGLE_OAUTH_REDIRECT_URI=https://<cloud-run-url>/api/v1/auth/google/callback" \
  --set-secrets="DB_PASSWORD=aeea-db-password:latest,SECURITY_TOKEN_ENCRYPTION_KEY=aeea-token-encryption-key:latest,GOOGLE_OAUTH_CLIENT_SECRET=aeea-google-oauth-secret:latest,AI_ANTHROPIC_API_KEY=aeea-anthropic-key:latest" \
  --allow-unauthenticated
```

`--min-instances=1` avoids Cloud Run's scale-to-zero for this service —
important here specifically because the in-process scheduler
(§8 of [`../ARCHITECTURE.md`](../ARCHITECTURE.md#8-background-jobs)) needs at
least one warm instance to actually fire scheduled jobs; scaling to zero
between requests would silently stop reminders/digests/polling. Redis-backed
leader election (`REDIS_HOST` above) is what makes `--max-instances` above 1
safe — see [`../DEPLOYMENT.md` §6](../DEPLOYMENT.md#6-scaling).

## 7. Frontend

Deploy `frontend/` to **Vercel** (native Next.js support, simplest option
regardless of backend host) or as its own Cloud Run service
(`frontend/Dockerfile`) with `NEXT_PUBLIC_API_BASE_URL` pointing at the
Cloud Run URL from step 6 (or your custom domain mapped to it via
`gcloud run domain-mappings create`).

## 8. CI/CD

Extend `.github/workflows/ci.yml` with a deploy job authenticating via
`google-github-actions/auth` (Workload Identity Federation, not a long-lived
JSON key) and running `gcloud run deploy` on `main`.
