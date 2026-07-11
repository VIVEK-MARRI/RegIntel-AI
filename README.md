<div align="center">

# RegIntel AI

**Multi-agent regulatory intelligence — hybrid retrieval, BGE reranking, knowledge graph, governance workflows, and RBAC — built on FastAPI + React.**

[![Version](https://img.shields.io/badge/version-10.0.0-6366f1?style=for-the-badge)](RELEASE_NOTES.md)
[![CI](https://img.shields.io/github/actions/workflow/status/VIVEK-MARRI/RegIntel-AI/ci.yml?branch=main&style=for-the-badge&label=CI&color=22c55e)](https://github.com/VIVEK-MARRI/RegIntel-AI/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11-3b82f6?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=for-the-badge&logo=fastapi&logoColor=white)](requirements.txt)
[![React](https://img.shields.io/badge/React-18.3-61dafb?style=for-the-badge&logo=react&logoColor=black)](frontend/package.json)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169e1?style=for-the-badge&logo=postgresql&logoColor=white)](docs/architecture/01-system-architecture.md)
[![License](https://img.shields.io/badge/license-MIT-f59e0b?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-2800%2B%20backend%20%7C%2047%20frontend-22c55e?style=for-the-badge)](docs/reviews/04-testing-review.md)

---

[Architecture](#-architecture-overview) &middot; [Query Flow](#-query-flow) &middot; [Multi-Agent System](#-multi-agent-system) &middot; [Quick Start](#-quick-start) &middot; [API Reference](#-api-reference) &middot; [Deployment](#-deployment) &middot; [Contributing](#-contributing)

</div>

---

## Why RegIntel AI

- **Grounded answers, not hallucinations.** Every response is tied to citations from the document corpus via a hallucination guard. The verifier rejects answers that reference chunks outside the evidence block.
- **Hybrid retrieval that actually works.** BM25 lexical search runs in parallel with pgvector HNSW dense search; results are fused via Reciprocal Rank Fusion and reranked by a BGE cross-encoder. Both paths are production code, not stubs.
- **Security-first from the start.** Custom HS256 JWT (no PyJWT dependency), 6 RBAC roles, 34 permissions, layered secrets management, 6-type threat detection, and a queryable audit log with SHA-256 evidence hashing.
- **Honest about its current limits.** No Kubernetes manifests yet. No Prometheus/Grafana. Redis is declared but not wired. These are tracked in the [Roadmap](#-roadmap--known-limitations) — not hidden.

---

## Architecture Overview

The system has three runtime layers: **Edge** (nginx + React SPA), **Application** (FastAPI, agent runtime, retrieval pipeline, knowledge graph, governance, security), and **Data** (PostgreSQL/pgvector, filesystem blob store).

```mermaid
flowchart LR
    classDef edge fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef app  fill:#dcfce7,stroke:#22c55e,color:#166534
    classDef data fill:#fef9c3,stroke:#eab308,color:#713f12
    classDef sec  fill:#fee2e2,stroke:#ef4444,color:#7f1d1d

    Browser["React SPA"]:::edge
    Nginx["nginx reverse proxy"]:::edge
    API["FastAPI"]:::app
    Agent["Agent runtime"]:::app
    Retrieval["Retrieval pipeline"]:::app
    KG["Knowledge graph"]:::app
    Workflow["Governance workflows"]:::app
    Security["Security platform"]:::sec
    PG[("PostgreSQL + pgvector")]:::data
    Blob[("Filesystem blobs + JSONL")]:::data
    LLM["LLM provider"]:::data

    Browser -->|HTTPS| Nginx
    Nginx -->|/api| API
    API --> Agent
    API --> Retrieval
    API --> KG
    API --> Workflow
    Security --> API
    Retrieval --> PG
    Agent --> PG
    Agent --> LLM
    Retrieval --> KG
    Workflow --> PG
    API --> Blob
```

| Layer | Components | Source |
|-------|-----------|--------|
| **Edge** | nginx (TLS, gzip, security headers, rate limit), React SPA | `nginx.conf`, `frontend/` |
| **Application** | FastAPI routers, agent runtime, hybrid retrieval, KG, governance, middleware | `app/` |
| **Security** | JWT auth, RBAC, secrets manager, API gateway, threat detection, audit log | `app/security/` |
| **Data** | PostgreSQL + pgvector (HNSW), filesystem blobs, LLM providers | `alembic/`, `storage/` |

---

## Query Flow

The retrieval pipeline runs BM25 and dense vector search concurrently, fuses results with Reciprocal Rank Fusion (k=60), then reranks with a BGE cross-encoder before passing evidence to the LLM.

```mermaid
flowchart LR
    classDef edge fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef app  fill:#dcfce7,stroke:#22c55e,color:#166534
    classDef data fill:#fef9c3,stroke:#eab308,color:#713f12
    classDef sec  fill:#fee2e2,stroke:#ef4444,color:#7f1d1d

    Q["User query"]:::edge
    Auth["JWT + RBAC"]:::sec
    RW["Query rewriter"]:::app
    BM25["BM25 search"]:::app
    VEC["Dense search pgvector"]:::app
    RRF["RRF fusion k=60"]:::app
    KGEXP["KG expansion"]:::app
    RERANK["BGE reranker"]:::app
    LLM["LLM provider"]:::data
    GUARD["Hallucination guard"]:::app
    OUT["Answer + citations"]:::edge

    Q --> Auth --> RW
    RW --> BM25
    RW --> VEC
    BM25 --> RRF
    VEC --> RRF
    RRF --> KGEXP --> RERANK --> LLM --> GUARD --> OUT
```

> **Default mode:** `LLM_PROVIDER=mock` returns structured placeholder answers with no API key required. Set `LLM_PROVIDER=openai` (or `gemini` / `litellm`) and provide `LLM_API_KEY` for real answer generation. This is a portfolio and evaluation project; the mock default is intentional.

---

## Multi-Agent System

The coordinator delegates to four real agents that share an in-process message bus and evidence store. All agent logic is implemented; LLM calls use the same provider abstraction (mock by default).

```mermaid
flowchart TB
    classDef app  fill:#dcfce7,stroke:#22c55e,color:#166534
    classDef data fill:#fef9c3,stroke:#eab308,color:#713f12

    Coord["CoordinatorAgent\nTaskPlanner + AgentRegistry"]:::app
    Research["ResearchAgent"]:::app
    Compliance["ComplianceAgent"]:::app
    Risk["RiskIntelligenceAgent"]:::app
    Audit["AuditAgent"]:::app
    Bus["AgentMessageBus\ntopic routing, history 500"]:::data
    Evidence["SharedEvidenceStore"]:::data
    WF["WorkflowEngine\nDRAFT to COMPLETED/FAILED"]:::data

    Coord --> Research
    Coord --> Compliance
    Coord --> Risk
    Coord --> Audit
    Research --> Bus
    Compliance --> Bus
    Risk --> Bus
    Audit --> Bus
    Bus --> Evidence
    Evidence --> WF
```

| Component | What it does | Source |
|-----------|-------------|--------|
| `CoordinatorAgent` | `BaseAgent(ABC)` + `AgentExecutionEngine` + `AgentRegistry` (JSONL persistence) | `app/services/agents/__init__.py` |
| `TaskPlanner` | Maps query keywords to `CapabilityKind`, produces `PlanStep` list | `app/services/agents/__init__.py:658` |
| `ResearchAgent` | Planner, executor, reasoner, report generator | `app/services/intelligence_agents/__init__.py:451` |
| `ComplianceAgent` | Analyzer, reasoner, recommendation generator | `app/services/intelligence_agents/__init__.py:878` |
| `RiskIntelligenceAgent` | Analyzer, forecast coordinator, scenario planner, report generator | `app/services/intelligence_agents/__init__.py:1280` |
| `AuditAgent` | Analyzer, evidence collector, reasoner, report generator | `app/services/audit_agent/__init__.py:535` |
| `AgentMessageBus` | In-process pub/sub, topic routing, bounded history (500 msgs) | `app/services/orchestration/__init__.py:82` |
| `WorkflowEngine` | State machine: `DRAFT→ACTIVE→PAUSED→COMPLETED/CANCELLED/FAILED` | `app/services/workflow/__init__.py:236` |

---

## Key Features

All claims cross-referenced against [`docs/reviews/claims-audit.md`](docs/reviews/claims-audit.md). Items marked FALSE or MISSING in that audit do not appear as working features here.

| Feature | Status | Notes |
|---------|--------|-------|
| BM25 lexical retrieval | Real | `rank_bm25.BM25Okapi`, persisted to `storage/bm25/bm25_index.pkl` |
| Dense vector retrieval | Real | pgvector HNSW index, `asyncpg` native queries |
| Hybrid retrieval (parallel) | Real | `asyncio.gather` concurrent BM25 + dense |
| RRF fusion | Real | `FusionEngine` + `RRFStrategy`, k=60, `1/(k+rank)` |
| BGE embeddings | Real | `BAAI/bge-small-en-v1.5`, 384-dim |
| BGE cross-encoder reranking | Real | `BAAI/bge-reranker-base`, lazy-loaded via `sentence-transformers` |
| Answer generation | Real | 4-section structured output; SSE streaming |
| OpenAI / Gemini / LiteLLM providers | Real | Requires API key; `LLM_PROVIDER=mock` is the safe default |
| Hallucination guard | Real | LLM faithfulness evaluator + lexical checker (60% cosine + 40% Jaccard) |
| 5-factor confidence scoring | Real | Deterministic heuristic; no LLM call |
| Knowledge graph — entity extraction | Real | Rule-based regex patterns (REGULATION, CIRCULAR, INSTITUTION, TOPIC, etc.) |
| Knowledge graph — BFS traversal | Real | `impact_traversal()` and `dependency_analysis()` |
| Knowledge graph — versioning/rollback | Real | Snapshot + restore via JSONL checkpoint |
| KG alias resolution | Missing | Not implemented; tracked in roadmap |
| Evaluation framework | Real | `AnswerEvaluator`, `AnswerBenchmarkRunner`, 8 metrics |
| Multi-agent framework (4 agents) | Real | Research, Compliance, Risk Intelligence, Audit |
| JWT auth (HS256) | Real | Custom `hmac` + `hashlib.sha256`; no PyJWT dependency |
| RBAC | Real | 6 roles, 34 permissions |
| Layered secrets | Real | env → file → vault stub; TTL cache; redaction |
| API gateway | Real | CORS, CIDR IP allowlist, HMAC-SHA256 request signing |
| Threat detection | Real | 6 types: brute force, path probing, large payload, suspicious UA, header abuse, rate anomaly |
| Audit log | Real | Queryable, JSONL/CSV export, SHA-256 evidence hashing |
| Multi-stage Docker | Real | `Dockerfile.production`, non-root, tini, health checks |
| Multi-arch images (amd64 + arm64) | Real | `release.yml` build-push |
| SBOM + provenance | Real | SPDX + attestations in release workflow |
| Trivy vulnerability scanning | Real | `aquasecurity/trivy-action` in CI + release |
| Prometheus / Grafana / OTEL | Planned | In-process counters only; no external export endpoints |
| Redis | Planned | Declared in config; rate limiter is in-process, not Redis |
| Kubernetes manifests | Planned | No `k8s/` directory |

---

## Tech Stack

### Backend

| Package | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.136.3 | HTTP framework, async routers |
| Pydantic | 2.13.4 | Data validation, settings |
| SQLAlchemy | 2.0.50 | ORM + async session |
| asyncpg | 0.31.0 | PostgreSQL async driver |
| pgvector | 0.4.2 | pgvector Python client |
| Alembic | 1.18.4 | Schema migrations |
| uvicorn | 0.32.0 | ASGI server |
| rank-bm25 | 0.2.2 | BM25Okapi implementation |
| PyMuPDF | 1.27.2.3 | PDF parsing |
| networkx | 3.6.1 | Knowledge graph traversal |

### Frontend

| Package | Version | Purpose |
|---------|---------|---------|
| React | ^18.3.1 | UI framework |
| Vite | ^5.4.10 | Build tooling |
| TypeScript | ^5.6.3 | Type safety |
| TanStack Query | ^5.59.0 | Server state management |
| React Router | ^6.27.0 | SPA routing |
| Recharts | ^2.13.0 | Data visualisation |
| Vitest | ^2.1.4 | Unit test runner |

### ML / Data

| Component | Detail |
|-----------|--------|
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim, CPU, `sentence-transformers`) |
| Reranker model | `BAAI/bge-reranker-base` (CrossEncoder, lazy-loaded) |
| Vector store | PostgreSQL + pgvector HNSW index |
| ML requirements | `requirements-ml.txt` — install separately; not in base Docker image |

### Infrastructure

| Component | Detail |
|-----------|--------|
| Reverse proxy | nginx 1.27-alpine |
| Containers | Docker + docker-compose (dev), `Dockerfile.production` (prod) |
| CI/CD | GitHub Actions — 11 jobs: lint, unit tests, evaluation, frontend, e2e, ml, migrations, integration, security, Docker build, coverage |
| Python | 3.11 |
| Node | 20 |

---

## Quick Start

### Option A — Docker (recommended for a quick look)

```bash
# 1. Clone and configure
git clone https://github.com/VIVEK-MARRI/RegIntel-AI.git
cd RegIntel-AI
cp .env.production.example .env
# Edit .env: set DATABASE_URL and REGINTEL_JWT_SECRET at minimum

# 2. Build the frontend
cd frontend && npm ci && npm run build && cd ..

# 3. Start the stack
docker compose up --build
# Backend API:  http://localhost:8000
# Frontend SPA: http://localhost:80
# Swagger docs: http://localhost:8000/docs
```

> The dev `docker-compose.yml` uses SQLite by default. For PostgreSQL + pgvector, set `DATABASE_URL=postgresql+asyncpg://...` in `.env`.

### Option B — Local Python

```bash
# 1. Create virtualenv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install base dependencies
pip install -r requirements.txt

# 3. (Optional) Install ML stack for real BGE embeddings and reranking
pip install -r requirements-ml.txt

# 4. Configure
cp .env.production.example .env
# Set: DATABASE_URL, REGINTEL_JWT_SECRET, LLM_PROVIDER

# 5. Run database migrations
alembic upgrade head

# 6. Start the backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. (Separate terminal) Start the frontend dev server
cd frontend && npm ci && npm run dev
```

### First query

```bash
# Health check
curl http://localhost:8000/health/live

# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Run a retrieval query (mock LLM response by default)
curl -X POST http://localhost:8000/api/v1/retrieval/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"capital requirements for tier 1 banks","top_k":5}'
```

<details>
<summary>Troubleshooting common setup issues</summary>

```
pgvector not found
  → Ensure the extension is enabled: CREATE EXTENSION IF NOT EXISTS vector;

ML models not downloaded on first run
  → BGE embedding + reranker models are ~100 MB; downloaded from Hugging Face on first use.
  → Set HF_HUB_OFFLINE=1 to fail fast if network is unavailable.

LLM_PROVIDER=mock (default)
  → Answers are structured placeholders, not AI-generated.
  → Set LLM_PROVIDER=openai and LLM_API_KEY=sk-... for real answers.

Frontend build missing
  → run `cd frontend && npm ci && npm run build` before starting Docker.
```

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more.

</details>

---

## Testing & Quality

| Suite | Test functions | Files | Runner |
|-------|---------------|-------|--------|
| Backend (unit + integration) | ~2,800 | 102 | pytest 9.0 |
| Frontend | 47 | 8 | Vitest 2.1 |

> **Methodology:** count of `def test_` and `async def test_` patterns across `tests/`. The [claims audit](docs/reviews/claims-audit.md) recorded 2,577 at its 2026-06-13 snapshot; the live codebase now returns ~2,800. Frontend count is 47 verified `it()`/`test()` calls across 8 test files.

```bash
# Backend unit suite (SQLite, no ML models required)
pytest tests \
  --ignore=tests/test_e2e \
  --ignore=tests/test_ml \
  -q --cov=app --cov-report=term-missing

# Frontend tests
cd frontend && npm test

# ML integration tests (downloads ~100 MB BGE models)
pytest tests/test_ml -v

# E2E pipeline tests
pytest tests/test_e2e -v
```

CI enforces `--cov-fail-under=80` on the backend unit suite. End-to-end browser tests (Cypress/Playwright) are not yet implemented.

---

## Security

All items below are verified in [docs/reviews/02-security-review.md](docs/reviews/02-security-review.md) and the [claims audit](docs/reviews/claims-audit.md).

- **JWT (HS256):** Custom `hmac.new()` + `hashlib.sha256` — no PyJWT dependency. Token refresh with rotation and revocation.
- **RBAC:** 6 roles (`VIEWER`, `ANALYST`, `OPERATOR`, `AUDITOR`, `ADMIN`, `SERVICE`), 34 permissions (13 read + 11 write + 9 operational + 1 special).
- **Password hashing:** PBKDF2-SHA256, 600K iterations, random salt.
- **Account lockout:** Configurable max attempts and duration, 429 response.
- **API gateway:** CORS strict-by-default, CIDR IP allowlist, HMAC-SHA256 request signing.
- **Threat detection (6 types):** Brute force, path probing, large payload, suspicious user-agent, header abuse, rate anomaly.
- **Layered secrets:** Resolution chain env → file → vault stub; TTL cache; value redaction in logs.
- **Audit log:** Every request logged; JSONL/CSV export; SHA-256 evidence hashing.
- **Docker hardening:** Non-root user (UID 10001), `no-new-privileges`, `cap_drop: ALL`, tmpfs for `/tmp`.
- **CI security gates:** Bandit static analysis, pip-audit dependency check, Trivy filesystem scan → SARIF upload.

**Known gaps (non-blocking):** no DB encryption at rest (delegate to managed PostgreSQL), vault integration is a stub, no mTLS between services.

---

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and [docs/architecture/04-deployment-architecture.md](docs/architecture/04-deployment-architecture.md) for full details.

### Required environment variables

| Variable | Required | Example |
|----------|----------|---------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host:5432/regintel` |
| `DATABASE_URL_SYNC` | Yes | `postgresql+psycopg2://user:pass@host:5432/regintel` |
| `REGINTEL_JWT_SECRET` | Yes | 32+ char random string |
| `STORAGE_ROOT` | Yes | `/var/lib/regintel/storage` |
| `LLM_PROVIDER` | Yes for real answers | `openai` / `gemini` / `litellm` |
| `LLM_API_KEY` | Yes if provider is not mock | `sk-...` |

<details>
<summary>Full environment variable reference</summary>

See [.env.production.example](.env.production.example) for all variables with descriptions. Key groups:

| Group | Variables |
|-------|-----------|
| Runtime | `ENV`, `LOG_LEVEL`, `WORKERS`, `PORT` |
| ML stack | `EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE`, `RERANKER_MODEL_NAME`, `RERANKER_TOP_N` |
| LLM | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT_SEC`, `ANSWER_STREAMING_ENABLED` |
| Security | `REGINTEL_CORS_ORIGINS`, `AUTH_MAX_FAILED_ATTEMPTS`, `AUTH_LOCKOUT_DURATION_SECONDS`, `SECURITY_DEV_TOKEN_ENDPOINT` |
| Rate limiting | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_PER_MINUTE` |
| Audit | `AUDIT_LOG_ENABLED`, `AUDIT_LOG_PERSIST`, `AUDIT_LOG_PATH` |

</details>

### Production checklist

```bash
# 1. Fill in the template
cp .env.production.example .env.production

# 2. Run migrations against the production database
alembic upgrade head

# 3. Start the production stack
docker compose -f docker-compose.production.yml up -d

# 4. Verify health
curl https://your-domain/health/ready
```

**External dependencies required for production:**
- Managed PostgreSQL with the `vector` extension enabled
- LLM API key (OpenAI, Google Gemini, or a LiteLLM proxy)
- HTTPS termination (nginx config provided, or place behind a load balancer)

---

## Roadmap / Known Limitations

These are **confirmed gaps**, not implied-as-done features.

| Item | Status | Notes |
|------|--------|-------|
| Kubernetes manifests | Planned | No `k8s/` directory; Docker + compose is the current deployment unit |
| Prometheus metrics export | Planned | In-process counters exist; no `/metrics` endpoint or `prometheus_client` |
| OpenTelemetry traces | Planned | `REGINTEL_OTEL_EXPORTER_OTLP_ENDPOINT` accepted but not wired |
| Grafana dashboards | Planned | Zero dashboard files in the repo |
| Redis (active use) | Planned | Config key exists; rate limiter is in-process, not Redis |
| KG alias resolution | Missing | No Jaro-Winkler or fuzzy matching implemented |
| Multi-replica state sharing | Missing | Rate limiter and message bus are per-process |
| E2E browser tests | Planned | `tests/test_e2e/` directory exists; no Cypress/Playwright driver yet |
| Structured JSON logging | Planned | Docker JSON-file driver handles rotation; app log lines are unstructured |
| IaC (Terraform/Pulumi) | Not started | |

---

## API Reference

<details>
<summary>Router groups and key endpoints</summary>

Interactive docs at `/docs` (Swagger UI) and `/redoc` when the server is running. Full reference: [docs/architecture/07-api-reference.md](docs/architecture/07-api-reference.md).

| Router | Prefix | Key endpoints |
|--------|--------|---------------|
| Auth | `/api/v1/auth` | `POST /login`, `POST /refresh`, `POST /logout` |
| Users | `/api/v1/users` | CRUD, role assignment |
| Documents | `/api/v1/documents` | `POST /` (upload + ingest), `GET /{id}` |
| Retrieval | `/api/v1/retrieval` | `POST /search` (hybrid BM25+vector), `POST /rerank` |
| Answer Generation | `/api/v1/answer-generation` | `POST /generate` (SSE streaming), `POST /generate/sync` |
| Knowledge Graph | `/api/v1/knowledge-graph` | `GET /entities`, `GET /relations`, `POST /query` |
| Agents | `/api/v1/agents` | `POST /run`, `GET /{run_id}`, registry |
| Governance | `/api/v1/governance` | `POST /decisions`, `POST /decisions/{id}/review` |
| Audit | `/api/v1/audit` | `GET /logs`, `GET /export` (JSONL/CSV) |
| Health | `/health` | `/live`, `/ready`, `/deep` |
| Benchmark | `/api/v1/benchmark` | `POST /run` (CLI: `python -m app.benchmark.cli --quick`) |

</details>

---

## Contributing

```bash
# Fork, clone, branch
git checkout -b feat/my-change

# Install dev dependencies
pip install -r requirements.txt
pip install ruff==0.7.4 mypy==1.13.0 pytest==9.0.3 pytest-asyncio==1.4.0 pytest-cov==7.1.0

# Lint and format
ruff check app tests
ruff format app tests

# Type check
mypy --ignore-missing-imports app/

# Run the unit test suite
pytest tests --ignore=tests/test_ml -q

# Submit a PR against main
```

Read [docs/architecture/08-developer-guide.md](docs/architecture/08-developer-guide.md) before contributing. New features must include tests and must not regress the `--cov-fail-under=80` gate.

---

## License & Acknowledgements

MIT License — Copyright (c) 2026 Vivek Marri. See [LICENSE](LICENSE).

**Key dependencies:**
- [FastAPI](https://fastapi.tiangolo.com/) — async Python web framework
- [pgvector](https://github.com/pgvector/pgvector) — PostgreSQL vector similarity search
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) — BM25Okapi implementation
- [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) — embedding model
- [BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base) — cross-encoder reranker
- [sentence-transformers](https://www.sbert.net/) — model loading and inference
- [React](https://react.dev/) + [Vite](https://vitejs.dev/) — frontend framework and build tool
