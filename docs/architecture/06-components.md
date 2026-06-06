# 06 — Component Reference

> Per-package responsibilities and dependencies. Use Ctrl-F to locate a
> module by name.

## `app.main`

The composition root. Builds the FastAPI application, registers every
router, wires module-level singletons (security, audit, benchmark) and
exposes `/health/live`, `/health/ready`, and `/metrics`.

| Symbol | Purpose |
|--------|---------|
| `app` | FastAPI instance |
| `_audit_log` | Module-level `AuditLog` (singleton) |
| `_security_jwt_issuer` | Module-level `JWTIssuer` |
| `_api_gateway` | Module-level `APIGateway` |

## `app.api.v1.*`

HTTP routers. Each module is a focused FastAPI `APIRouter` mounted
under `/api/v1/<name>`.

| Module | Path | Purpose |
|--------|------|---------|
| `retrieval` | `/api/v1/retrieval` | Hybrid search + RAG |
| `documents` | `/api/v1/documents` | Document CRUD, versions |
| `agent` | `/api/v1/agent` | Agent run, history |
| `governance` | `/api/v1/governance` | Decisions, review |
| `knowledge_graph` | `/api/v1/kg` | Entity/relation query |
| `security` | `/api/v1/security` | JWT, RBAC, audit, threat |
| `benchmark` | `/api/v1/benchmark` | Performance, load, latency |
| `monitoring` | `/api/v1/monitoring` | Health, metrics, alerts |
| `analytics` | `/api/v1/analytics` | Usage, cost, feedback |
| `api_keys` | `/api/v1/api-keys` | API key management |
| `chunks` | `/api/v1/chunks` | Direct chunk access (admin) |
| `embeddings` | `/api/v1/embeddings` | Vector search / embed |
| `feedback` | `/api/v1/feedback` | User feedback capture |
| `glossary` | `/api/v1/glossary` | Controlled vocabulary |
| `health` | `/api/v1/health` | Basic liveness |
| `intake` | `/api/v1/intake` | Ingestion submission |
| `parser` | `/api/v1/parser` | Parse + chunk on demand |
| `rag` | `/api/v1/rag` | Synchronous RAG endpoint |
| `router` | `/api/v1/router` | Query routing |
| `search` | `/api/v1/search` | Faceted search |
| `tools` | `/api/v1/tools` | Tool catalog |
| `versioning` | `/api/v1/versioning` | Document versions |
| `workflows` | `/api/v1/workflows` | Workflow definitions |
| `costs` | `/api/v1/costs` | Cost breakdown |
| `errors` | `/api/v1/errors` | Error catalog |
| `system` | `/api/v1/system` | System info |
| `query` | `/api/v1/query` | NL query |

(For the full list, run `python -c "import app.main; print([r.path for r in app.main.app.routes])"`.)

## `app.agent`

RAG agent runtime. Sub-modules:

* `app.agent.rewriter` — query rewriting
* `app.agent.planner` — tool-use planner
* `app.agent.composer` — answer composer
* `app.agent.verifier` — post-generation check
* `app.agent.tools` — tool implementations
* `app.agent.runner` — async runner
* `app.agent.history` — conversation memory

## `app.retrieval`

Hybrid retrieval. Sub-modules:

* `app.retrieval.hybrid` — vector + lexical fusion
* `app.retrieval.reranker` — cross-encoder reranking
* `app.retrieval.evaluation` — offline metrics
* `app.retrieval.embedding_cache` — embedding LRU

## `app.knowledge_graph`

* `app.knowledge_graph.extractor` — LLM-based entity / relation
  extraction
* `app.knowledge_graph.normaliser` — alias resolution, dedup
* `app.knowledge_graph.query` — graph traversal API
* `app.knowledge_graph.versioning` — graph versions

## `app.governance`

* `app.governance.service` — decision CRUD
* `app.governance.workflow` — state machine
* `app.governance.review` — review queue

## `app.security`

The M10.6 security platform.

* `app.security.jwt_auth` — RFC 7519 HS256 JWT (no PyJWT dep)
* `app.security.rbac` — `Role`, `Permission`, `Principal`
* `app.security.secrets` — layered secret resolution
* `app.security.api_gateway` — CORS, IP allowlist, request signing
* `app.security.threat_detection` — pattern + brute-force detection
* `app.security.audit_review` — query/filter/export the audit log
* `app.security.monitoring` — aggregate security dashboard
* `app.security.api` — FastAPI router under `/api/v1/security`

## `app.benchmark`

The M10.5 performance benchmark.

* `app.benchmark.models` — Pydantic schemas
* `app.benchmark.metrics_collector` — portable metrics
* `app.benchmark.performance_runner` — single-shot timing
* `app.benchmark.load_tester` — concurrent load
* `app.benchmark.benchmark_service` — orchestrator (singleton)
* `app.benchmark.reporter` — JSON / markdown / HTML reports
* `app.benchmark.api` — FastAPI router under `/api/v1/benchmark`
* `app.benchmark.cli` — `python -m app.benchmark.cli`

## `app.middleware`

* `AuditLog` / `AuditLogEntry` — in-memory + JSONL audit
* `APIKey` / `APIKeyStore` — API key storage
* `RateLimiter` — sliding-window rate limit
* `RequestIDMiddleware` — X-Request-ID propagation

## `app.llm`

* `app.llm.client` — provider-agnostic LLM client
* `app.llm.embeddings` — embedding provider
* `app.llm.prompts` — prompt templates

## `app.parsing`

PDF / DOCX / HTML / text parsing.

## `app.chunking`

Sliding-window + semantic chunking.

## `app.storage`

Object storage abstraction (S3, GCS, Azure Blob).

## `app.analytics`

Usage, cost, and feedback tracking.

## `app.migrations` / `alembic`

Database migrations. Use `alembic upgrade head` to apply.

## `app.cache`

In-process LRU + optional Redis backend.

## `tests/`

* `tests/test_security.py` — M10.6 unit tests
* `tests/test_security_api.py` — M10.6 HTTP tests
* `tests/test_benchmark.py` — M10.5 unit tests
* `tests/test_benchmark_api.py` — M10.5 HTTP tests
* `tests/test_deployment.py` — M10.3 deployment validation
* `tests/test_pipeline.py` — M10.4 CI pipeline validation
* (Prior milestones: `test_milestone{1..9}.py` etc.)

## See also

* [Architecture index](./README.md)
* [01 — System Architecture](./01-system-architecture.md)
* [05 — Data Flow](./05-data-flow.md)
* [07 — API Reference](./07-api-reference.md)
