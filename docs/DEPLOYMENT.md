# Deployment Guide

> Step-by-step deployment of RegIntel AI v1.0.0 to a production
> environment. Read this end-to-end before running any commands.

## 1. Prerequisites

* A Linux host (or Kubernetes cluster) with Docker 24+ and
  docker compose 2.20+ (or Kubernetes 1.27+).
* PostgreSQL 16+ with the `pgvector` extension installed and a
  database created.
* An object storage bucket (S3, GCS, Azure Blob) for raw documents.
* An LLM provider (Azure OpenAI, AWS Bedrock, or a self-hosted
  OpenAI-compatible endpoint).
* A reverse proxy / load balancer for TLS termination (or use the
  bundled `frontend` container which is TLS-ready).
* A DNS name pointing to your edge.

## 2. Prepare the secrets

The backend requires a JWT secret of at least 32 characters. Generate
one with:

```bash
openssl rand -base64 48 | tr -d '\n=' | head -c 64
```

Store every secret in your secret manager (AWS Secrets Manager,
HashiCorp Vault, Kubernetes Secrets, etc.):

| Name | Required | Notes |
|------|----------|-------|
| `REGINTEL_JWT_SECRET` | yes | ≥ 32 chars |
| `REGINTEL_DB_URL` | yes | `postgresql+asyncpg://user:pass@host:5432/db` |
| `REGINTEL_OBJECT_STORE_BUCKET` | yes | bucket name |
| `REGINTEL_OBJECT_STORE_ACCESS_KEY` | yes | access key |
| `REGINTEL_OBJECT_STORE_SECRET_KEY` | yes | secret key |
| `REGINTEL_LLM_PROVIDER` | yes | `azure_openai` / `bedrock` / `openai` |
| `REGINTEL_LLM_API_KEY` | yes | provider key |
| `REGINTEL_LLM_ENDPOINT` | no | for Azure / self-hosted |
| `REGINTEL_OTEL_EXPORTER_OTLP_ENDPOINT` | no | OTLP endpoint for traces |
| `REGINTEL_CORS_ORIGINS` | yes | comma-separated list of allowed origins |
| `REGINTEL_VAULT_URL` | no | Vault URL for secret resolution |
| `REGINTEL_VAULT_TOKEN` | no | Vault token |

## 3. Configure the environment

Copy `.env.production.example` to `.env.production` and fill in every
value. **Never** commit the filled file.

```bash
cp .env.production.example .env.production
$EDITOR .env.production
```

The application will refuse to start if any required variable is
missing or if the JWT secret is too short.

## 4. Apply the database schema

```bash
docker compose -f docker-compose.production.yml run --rm backend \
  alembic upgrade head
```

This runs every pending migration in `alembic/versions/`.

## 5. Pull and start the stack

```bash
docker compose -f docker-compose.production.yml pull
docker compose -f docker-compose.production.yml up -d
```

Verify that both services are healthy:

```bash
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs --tail 100 backend
```

## 6. Smoke test

```bash
# Liveness
curl -f https://<host>/health/live

# Readiness
curl -f https://<host>/health/ready

# Security self-test
curl -f https://<host>/api/v1/security/selftest

# Benchmark health
curl -f https://<host>/api/v1/benchmark/health

# Issue a dev token (only available when SECURITY_DEV_TOKEN_ENDPOINT=true)
curl -X POST https://<host>/api/v1/security/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"subject": "smoketest", "roles": ["admin"]}'
```

## 7. Disable the dev token endpoint

Before going live:

```bash
# Edit .env.production
SECURITY_DEV_TOKEN_ENDPOINT=false

# Restart the backend
docker compose -f docker-compose.production.yml up -d --force-recreate backend
```

After this, the only way to obtain a JWT is via your identity
provider. The platform's `JWTIssuer` is a small HS256 implementation
designed to be replaceable; integrate with Auth0, Okta, Keycloak, or
AWS Cognito at your proxy.

## 8. Configure the reverse proxy

### Cloud load balancer (recommended)

* Terminate TLS at the LB.
* Forward to the `frontend` container on port 80 (the bundled nginx
  serves HTTPS itself, but you can also forward plain HTTP from the
  LB and let nginx add the headers).
* Set up health checks on `/health/live` (port 80).

### Bundled nginx (small deployments)

* Mount a TLS certificate at `/etc/nginx/certs/<host>.crt` and
  `/etc/nginx/certs/<host>.key` inside the `frontend` container.
* Update `nginx.conf` to enable the HTTPS server block (currently
  commented out).
* Restart the frontend container.

## 9. Configure backups

| Resource | Tool | Schedule |
|----------|------|----------|
| PostgreSQL | `pg_basebackup` + WAL | Hourly + continuous |
| Object storage | Provider versioning | Continuous |
| Audit log | `tar` to object storage | Daily |
| Secrets | Vault backup | Daily |

The on-call runbook in `docs/architecture/09-operations-guide.md` has
the full recovery procedure.

## 10. Roll out

1. Deploy to a staging environment first.
2. Run the benchmark suite:
   `curl -X POST https://<host>/api/v1/benchmark/run -d '{"suite":"quick"}'`.
3. Compare against the baseline in `docs/architecture/04-deployment-architecture.md#scaling`.
4. Promote to production with a blue / green or canary strategy.

## 11. Verify

* Open `https://<host>/` in a browser.
* Sign in (via your IDP).
* Ask a question; confirm citations are present.
* Check `/api/v1/security/audit/records?status_min=200` for the
  successful request.

## 12. Subscribe to updates

* GitHub releases: watch `regintel/regintel-ai` for `vX.Y.Z` tags.
* Slack: `#regintel-releases`.
* RSS: `https://github.com/regintel/regintel-ai/releases.atom`.
