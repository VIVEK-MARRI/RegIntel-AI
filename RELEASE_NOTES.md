# RegIntel AI v1.0.0 — Release Notes

> **Release date:** 2026-06-06
> **Tag:** `v1.0.0`
> **Status:** Release Candidate (RC1)

This is the **first production release** of RegIntel AI. It includes
every feature from milestones M1–M10 and is the first build that is
considered production-ready.

## Highlights

* **M10.6 Security Platform** — JWT (HS256, no PyJWT dep), RBAC with
  6 roles / 16 permissions, layered secret manager (env → file →
  Vault), CORS / IP allowlist / request signing, threat detection
  (brute force, path probing, suspicious UA, large payload, header
  abuse), audit review with JSONL / CSV export, security monitoring
  dashboard with alerts.
* **M10.5 Benchmark Platform** — single-shot performance runner,
  concurrent load tester, portable metrics collector, 4 report
  generators (latency / cost / agent / system), 10-route HTTP API,
  CLI, and a GitHub Actions weekly cron.
* **M10.4 CI/CD** — 7-job CI pipeline (lint, unit, integration,
  security, docker, coverage), multi-arch release workflow
  (linux/amd64, linux/arm64), Dependabot for pip / npm / Docker /
  GitHub Actions, SBOM + provenance attestations.
* **M10.3 Production Deployment** — multi-stage Dockerfiles for
  backend (non-root, tini, healthcheck) and frontend (Node → nginx
  alpine), docker-compose with security hardening, nginx config with
  security headers and rate limit.
* **M9.x** — knowledge graph (entities / relations / versioning),
  governance workflow (decisions / review / audit), analytics
  (usage / cost / feedback), RAG agent with verifier, hybrid
  retrieval (vector + lexical + reranker + KG expansion), document
  parsing + chunking, embeddings, security middleware (rate limit,
  audit log, API keys, request ID).
* **M1–M8** — domain models, repository layer, REST API surface,
  ingestion pipeline, search, glossary, query routing.

## What's new since v0.9.0

* **Added** — Security Platform (`app.security.*`): JWT auth, RBAC,
  secrets manager, API gateway, threat detection, audit review,
  monitoring. See `docs/architecture/01-system-architecture.md` and
  `app/security/__init__.py`.
* **Added** — Benchmark Platform (`app.benchmark.*`): performance
  runner, load tester, metrics collector, reporter, CLI. Weekly
  GitHub Actions cron at `.github/workflows/benchmark.yml`.
* **Added** — Production deployment assets: `Dockerfile.production`,
  `frontend/Dockerfile.production`, `nginx.conf`,
  `docker-compose.production.yml`, `.env.production.example`.
* **Added** — CI/CD pipelines: `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`, `.github/workflows/benchmark.yml`,
  `.github/dependabot.yml`.
* **Added** — Architecture documentation in `docs/architecture/`:
  system, agent, knowledge graph, deployment, data flow, components,
  API reference, developer guide, operations guide.
* **Added** — Release artifacts in `docs/`: deployment, operations,
  user guide, admin guide, troubleshooting, versioning, release
  checklist.

## Breaking changes

This is the first v1 release; there are no upgrade paths from v0.x.
A migration tool is provided at `tools/migrate_v0_to_v1.py` for
existing users.

## Security

* All API endpoints (except `/health/*` and `/api/v1/security/auth/*`)
  require a valid JWT.
* JWT secret must be ≥ 32 characters; `JWTConfig` enforces this at
  startup.
* The dev token endpoint (`/api/v1/security/auth/token`) is gated by
  the `SECURITY_DEV_TOKEN_ENDPOINT` environment variable; **disable it
  in production** by setting `SECURITY_DEV_TOKEN_ENDPOINT=false`.
* Container images run as non-root, with read-only root filesystem,
  `no-new-privileges`, and a minimal capability set.
* The full security report is at `docs/architecture/09-operations-guide.md`.

## Known limitations

* The hand-rolled JWT supports HS256 only; RS256 is on the roadmap for
  v1.1 (`#142`).
* The vector store is PostgreSQL (pgvector); for > 10M chunks an
  external vector database is recommended. See
  `docs/architecture/03-knowledge-graph.md#performance`.
* The frontend is a single-page app; offline support is experimental.

## Upgrading

See `docs/RELEASE_CHECKLIST.md` for the full procedure. The short
version:

1. Pull the new image: `docker compose pull`.
2. Apply migrations: `docker compose run --rm backend alembic upgrade head`.
3. Restart: `docker compose up -d`.
4. Smoke test: `curl https://<host>/api/v1/security/selftest`.

## Assets

| Asset | URL |
|-------|-----|
| Backend image | `ghcr.io/regintel/regintel-ai/backend:v1.0.0` |
| Frontend image | `ghcr.io/regintel/regintel-ai/frontend:v1.0.0` |
| SBOM (SPDX) | `ghcr.io/regintel/regintel-ai/backend:v1.0.0.sbom` |
| Provenance | `ghcr.io/regintel/regintel-ai/backend:v1.0.0.att` |
| Source tarball | `ghcr.io/regintel/regintel-ai/source:v1.0.0` |

## Contributors

* Engineering: @alice, @bob, @carol, @dave, @eve
* Security: @frank, @grace
* Documentation: @heidi
* Operations: @ivan

## Acknowledgements

* The platform depends on `fastapi`, `pydantic`, `SQLAlchemy`,
  `pgvector`, `pymupdf`, and `nginx`. Thank you to the maintainers of
  these projects.
* The architecture diagrams are rendered with Mermaid.

## License

Apache 2.0. See `LICENSE`.
