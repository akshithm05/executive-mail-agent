# Deploying to Azure (Container Apps)

Assumes you've read [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — this covers only
what's Azure-specific. Target topology: Container Apps for the API, Azure
Database for PostgreSQL Flexible Server, Azure Cache for Redis, Key Vault
for secrets, Azure Container Registry for images.

## 1. Prerequisites

```bash
az login
az account set --subscription <subscription-id>
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.DBforPostgreSQL
az provider register --namespace Microsoft.Cache

RG=aeea-rg
LOCATION=eastus
az group create --name $RG --location $LOCATION
```

## 2. Push the image to ACR

```bash
az acr create --resource-group $RG --name aeearegistry --sku Basic
az acr login --name aeearegistry

cd backend
docker build -t aeearegistry.azurecr.io/aeea-backend:latest .
docker push aeearegistry.azurecr.io/aeea-backend:latest
```

## 3. Provision data stores

```bash
# Postgres (Flexible Server)
az postgres flexible-server create \
  --resource-group $RG --name aeea-postgres \
  --location $LOCATION \
  --admin-user aeea --admin-password '<db-password>' \
  --sku-name Standard_B1ms --tier Burstable \
  --version 16 --storage-size 32 \
  --database-name aeea \
  --public-access none

# Redis -- optional but recommended for >1 replica (see
# ../DEPLOYMENT.md §6: it backs the scheduler leader election).
az redis create --resource-group $RG --name aeea-redis \
  --location $LOCATION --sku Basic --vm-size c0
```

## 4. Store secrets in Key Vault

```bash
az keyvault create --resource-group $RG --name aeea-kv --location $LOCATION

az keyvault secret set --vault-name aeea-kv --name db-password --value '<db-password>'
az keyvault secret set --vault-name aeea-kv --name token-encryption-key \
  --value "$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
az keyvault secret set --vault-name aeea-kv --name google-oauth-secret --value '<client-secret>'
az keyvault secret set --vault-name aeea-kv --name anthropic-key --value '<api-key>'
```

## 5. Create the Container Apps environment

```bash
az containerapp env create \
  --resource-group $RG --name aeea-env --location $LOCATION
```

## 6. Run the migration (once, before deploying the long-running app)

Container Apps Jobs is the right primitive for a one-shot task:

```bash
az containerapp job create \
  --resource-group $RG --name aeea-migrate \
  --environment aeea-env \
  --image aeearegistry.azurecr.io/aeea-backend:latest \
  --registry-server aeearegistry.azurecr.io \
  --trigger-type Manual --replica-timeout 300 \
  --env-vars DB_HOST=aeea-postgres.postgres.database.azure.com DB_NAME=aeea DB_USER=aeea \
  --secrets db-password=keyvaultref:https://aeea-kv.vault.azure.net/secrets/db-password,identityref:system \
  --command "alembic" --args "upgrade" "head"

az containerapp job start --resource-group $RG --name aeea-migrate
```

## 7. Deploy the API app

```bash
az containerapp create \
  --resource-group $RG --name aeea-backend \
  --environment aeea-env \
  --image aeearegistry.azurecr.io/aeea-backend:latest \
  --registry-server aeearegistry.azurecr.io \
  --target-port 8000 --ingress external \
  --min-replicas 1 --max-replicas 10 \
  --env-vars \
    ENVIRONMENT=production \
    DB_HOST=aeea-postgres.postgres.database.azure.com \
    DB_NAME=aeea DB_USER=aeea \
    REDIS_HOST=aeea-redis.redis.cache.windows.net \
    SESSION_COOKIE_SECURE=true \
    CORS_ORIGINS=https://your-frontend-domain.example \
    GOOGLE_OAUTH_CLIENT_ID=<client-id> \
    GOOGLE_OAUTH_REDIRECT_URI=https://<container-app-fqdn>/api/v1/auth/google/callback \
  --secrets \
    db-password=keyvaultref:https://aeea-kv.vault.azure.net/secrets/db-password,identityref:system \
    token-key=keyvaultref:https://aeea-kv.vault.azure.net/secrets/token-encryption-key,identityref:system \
    oauth-secret=keyvaultref:https://aeea-kv.vault.azure.net/secrets/google-oauth-secret,identityref:system \
    anthropic-key=keyvaultref:https://aeea-kv.vault.azure.net/secrets/anthropic-key,identityref:system
```

`--min-replicas 1` keeps at least one instance always warm — the in-process
scheduler ([`../ARCHITECTURE.md` §8](../ARCHITECTURE.md#8-background-jobs))
needs a running instance to fire scheduled jobs; scaling to zero would
silently stop reminders/digests/polling. Redis-backed leader election is
what makes `--max-replicas` above 1 safe (see
[`../DEPLOYMENT.md` §6](../DEPLOYMENT.md#6-scaling)).

Configure the liveness/readiness probes against `/api/v1/health/live` and
`/api/v1/health/ready` via `az containerapp update --yaml` (probes aren't
exposed as flags on `create`) — see Azure's Container Apps health-probes
documentation for the YAML shape.

## 8. Frontend

Deploy `frontend/` to **Azure Static Web Apps** (native Next.js support) or
as its own Container App, with `NEXT_PUBLIC_API_BASE_URL` pointing at the
Container App's FQDN from step 7.

## 9. CI/CD

Extend `.github/workflows/ci.yml` with a deploy job authenticating via
`azure/login` (OIDC federated credentials, not a stored client secret) and
running `az acr build` + `az containerapp update --image ...` on `main`.
