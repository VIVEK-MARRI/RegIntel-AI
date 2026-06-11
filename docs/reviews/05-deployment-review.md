# Deployment Review — Release Candidate

## Artifacts

| Artifact | Status | Notes |
|----------|--------|-------|
| Dockerfile (backend) | ✅ | Multi-stage, non-root, tini, HEALTHCHECK, uvicorn |
| Dockerfile (frontend) | ✅ | Multi-stage, nginx:alpine, ~40 MB image |
| docker-compose | ✅ | Resource limits, security hardening, health gates |
| nginx.conf | ✅ | Gzip, rate limiting, CSP, caching, SPA fallback |
| .env.production.example | ✅ | All configurable vars documented |
| Deployment docs | ✅ | DEPLOYMENT.md, architecture docs, operations guide |

## Health Checks

| Endpoint | Type | Proto |
|----------|------|-------|
| `/health/live` | Liveness | Always 200 |
| `/health/ready` | Readiness | Checks liveness + storage + env + database |
| `/health/deep` | Deep | All registered components |
| `/health` | Simple | Legacy `{"status": "ok"}` |

## Resource Limits

| Service | CPU | Memory | tmpfs |
|---------|-----|--------|-------|
| Backend | 2.0 (res: 0.5) | 2G (res: 512M) | 64M |
| Frontend | 0.5 (res: 0.1) | 256M (res: 64M) | — |

## Security Hardening in Docker

- `no-new-privileges: true`
- `cap_drop: ALL` + `cap_add: NET_BIND_SERVICE`
- Non-root user (UID 10001 backend, nginx frontend)
- tmpfs for `/tmp` (backend)
- `restart: unless-stopped`
- JSON-file logging with rotation (20 MB, 5 files)

## CI/CD (GitHub Actions)

| Workflow | Status |
|----------|--------|
| CI (tests + lint) | ✅ |
| Release (multi-arch build) | ✅ |
| SBOM generation | ✅ |
| Provenance attestation | ✅ |
| Trivy vulnerability scan | ✅ |

## Startup Validation

- Required env vars checked before serving
- Storage writability verified
- Database connectivity checked (health endpoint)
- Detailed StartupReport with errors/warnings/registered components

## Gaps

| Gap | Priority | Notes |
|-----|----------|-------|
| No Kubernetes manifests | Low | k8s adapters can reference Docker + docs |
| No Terraform/Pulumi IaC | Low | Docs reference the pattern |
| No automated DB migrations in startup | Medium | Must run manually via compose |
| No structured JSON logging in code | Low | Docker JSON-file driver handles rotation |
