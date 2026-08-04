# Deploying to AWS (ECS Fargate)

Assumes you've read [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — this covers only
what's AWS-specific. Target topology: ECS Fargate for the API (and a
one-shot migration task), RDS for Postgres, ElastiCache for Redis, ALB in
front, Secrets Manager for secrets, ECR for images.

## 1. Prerequisites

```bash
aws --version   # AWS CLI v2
aws sts get-caller-identity   # confirm you're authenticated
```

Pick a region (examples below use `us-east-1`) and have a VPC with at least
two private subnets (for RDS/ElastiCache/Fargate tasks) and two public
subnets (for the ALB) — the default VPC works for a first deployment.

## 2. Push the image to ECR

```bash
aws ecr create-repository --repository-name aeea-backend
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com

cd backend
docker build -t aeea-backend:latest .
docker tag aeea-backend:latest \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/aeea-backend:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/aeea-backend:latest
```

## 3. Provision data stores

```bash
# Postgres (RDS) -- adjust instance class/storage for your load.
aws rds create-db-instance \
  --db-instance-identifier aeea-postgres \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t4g.micro \
  --allocated-storage 20 \
  --master-username aeea --master-user-password '<generate-one>' \
  --db-name aeea \
  --vpc-security-group-ids <sg-allowing-5432-from-ecs-tasks> \
  --db-subnet-group-name <your-private-subnet-group> \
  --no-publicly-accessible \
  --backup-retention-period 7

# Redis (ElastiCache) -- optional but recommended for >1 replica (see
# ../DEPLOYMENT.md §6 on why: it backs the scheduler leader election).
aws elasticache create-cache-cluster \
  --cache-cluster-id aeea-redis \
  --engine redis --engine-version 7.1 \
  --cache-node-type cache.t4g.micro \
  --num-cache-nodes 1 \
  --security-group-ids <sg-allowing-6379-from-ecs-tasks> \
  --cache-subnet-group-name <your-private-subnet-group>
```

## 4. Store secrets

```bash
aws secretsmanager create-secret --name aeea/db-password --secret-string '<db-password>'
aws secretsmanager create-secret --name aeea/token-encryption-key \
  --secret-string "$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
aws secretsmanager create-secret --name aeea/google-oauth-client-secret --secret-string '<client-secret>'
aws secretsmanager create-secret --name aeea/anthropic-api-key --secret-string '<api-key>'
```

## 5. ECS task definition

Two containers share this shape — the API (long-running service) and the
migration (one-shot `RunTask`, same image, different `command`). Non-secret
config goes in `environment`; anything sensitive is a `secrets` reference
resolved at task launch, never baked into the image or logged.

```json
{
  "family": "aeea-backend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::<account-id>:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::<account-id>:role/aeeaTaskRole",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "<account-id>.dkr.ecr.us-east-1.amazonaws.com/aeea-backend:latest",
      "portMappings": [{ "containerPort": 8000 }],
      "environment": [
        { "name": "ENVIRONMENT", "value": "production" },
        { "name": "DB_HOST", "value": "<rds-endpoint>" },
        { "name": "DB_PORT", "value": "5432" },
        { "name": "DB_USER", "value": "aeea" },
        { "name": "DB_NAME", "value": "aeea" },
        { "name": "REDIS_HOST", "value": "<elasticache-endpoint>" },
        { "name": "SESSION_COOKIE_SECURE", "value": "true" },
        { "name": "CORS_ORIGINS", "value": "https://your-frontend-domain.example" },
        { "name": "GOOGLE_OAUTH_CLIENT_ID", "value": "<client-id>" },
        { "name": "GOOGLE_OAUTH_REDIRECT_URI", "value": "https://api.your-domain.example/api/v1/auth/google/callback" }
      ],
      "secrets": [
        { "name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:us-east-1:<account-id>:secret:aeea/db-password" },
        { "name": "SECURITY_TOKEN_ENCRYPTION_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:<account-id>:secret:aeea/token-encryption-key" },
        { "name": "GOOGLE_OAUTH_CLIENT_SECRET", "valueFrom": "arn:aws:secretsmanager:us-east-1:<account-id>:secret:aeea/google-oauth-client-secret" },
        { "name": "AI_ANTHROPIC_API_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:<account-id>:secret:aeea/anthropic-api-key" }
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/health/live || exit 1"],
        "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 10
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/aeea-backend",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "api"
        }
      }
    }
  ]
}
```

```bash
aws logs create-log-group --log-group-name /ecs/aeea-backend
aws ecs register-task-definition --cli-input-json file://aeea-task-def.json
```

## 6. Run the migration (once, before the service starts serving)

```bash
aws ecs run-task \
  --cluster aeea-cluster \
  --task-definition aeea-backend \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<private-subnet-ids>],securityGroups=[<sg>],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["alembic","upgrade","head"]}]}'
```

Wait for it to exit 0 (`aws ecs describe-tasks`) before proceeding.

## 7. Create the service + ALB

```bash
aws ecs create-cluster --cluster-name aeea-cluster

aws elbv2 create-target-group \
  --name aeea-api-tg --protocol HTTP --port 8000 --vpc-id <vpc-id> \
  --target-type ip \
  --health-check-path /api/v1/health/ready \
  --health-check-interval-seconds 15

aws elbv2 create-load-balancer \
  --name aeea-alb --subnets <public-subnet-ids> --security-groups <sg-allowing-443>

# Attach an HTTPS listener (ACM cert) forwarding to the target group, then:
aws ecs create-service \
  --cluster aeea-cluster \
  --service-name aeea-api \
  --task-definition aeea-backend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<private-subnet-ids>],securityGroups=[<sg>],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<tg-arn>,containerName=api,containerPort=8000" \
  --health-check-grace-period-seconds 30
```

`desired-count 2` is exactly the scaling story from
[`../DEPLOYMENT.md` §6](../DEPLOYMENT.md#6-scaling) — both replicas run the
scheduler, only one (Redis-elected) fires jobs. Scale further with
`aws ecs update-service --desired-count N`, or attach Application
Auto Scaling on CPU/request-count.

## 8. Frontend

Simplest path: deploy `frontend/` to **AWS Amplify Hosting** (native Next.js
support, builds from source, no image to manage) with
`NEXT_PUBLIC_API_BASE_URL` pointing at the ALB's domain. Alternatively, push
`frontend/Dockerfile`'s image to ECR the same way as the backend (§2) and run
it as a second Fargate service — the frontend is entirely client-rendered
(no server components in the data path — see
[`../ARCHITECTURE.md` §13](../ARCHITECTURE.md#13-frontend)), so it needs no
special network access to the VPC's private resources, only a route to the
API's public ALB.

## 9. CI/CD

Extend `.github/workflows/ci.yml` with a deploy job gated on `main`,
authenticating via `aws-actions/configure-aws-credentials` (OIDC, not a
long-lived access key) and running the ECR push + `aws ecs update-service
--force-new-deployment` steps above.
