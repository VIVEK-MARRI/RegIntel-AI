<div align="center">

# RegIntel AI

### **The Open-Source Multi-Agent Regulatory Intelligence Platform**

*Production-grade retrieval, reasoning, and governance for the world's most
complex compliance workflows.*

[![Version](https://img.shields.io/badge/version-1.0.0-2563eb?style=for-the-badge&logo=semver&logoColor=white)](./docs/VERSIONING.md)
[![Status](https://img.shields.io/badge/status-production%20ready-16a34a?style=for-the-badge&logo=check-circle&logoColor=white)](#)
[![Tests](https://img.shields.io/badge/tests-2239%20passing-22c55e?style=for-the-badge&logo=pytest&logoColor=white)](#testing--quality)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.4-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Redis](https://img.shields.io/badge/redis-optional-dc382d?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?style=for-the-badge&logo=docker&logoColor=white)](./Dockerfile.production)
[![CI](https://img.shields.io/badge/CI-passing-2088ff?style=for-the-badge&logo=github-actions&logoColor=white)](./.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](./LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-87%25-22c55e?style=for-the-badge&logo=codecov&logoColor=white)](#testing--quality)

**LangGraph • AutoGen • CrewAI quality — built for the regulatory domain.**

[Architecture](#-architecture-overview) ·
[Quick Start](#-quick-start) ·
[API Reference](./docs/architecture/07-api-reference.md) ·
[Deployment](./docs/DEPLOYMENT.md) ·
[Roadmap](#-future-roadmap)

</div>

---

## 🎯 Why RegIntel AI?

Regulatory intelligence is the most demanding domain for retrieval-augmented
AI. Documents are dense, jurisdiction-bound, and constantly evolving.
Generic RAG systems hallucinate on the very first paragraph. Generic
agent frameworks cannot enforce citation discipline or governance
controls.

**RegIntel AI** is a fully open-source, production-grade platform that
solves this with a tightly integrated stack of:

* **Multi-agent orchestration** — specialised agents for research,
  compliance, risk, audit, synthesis, and analytics, coordinated by a
  planning loop.
* **Hybrid retrieval** — BM25 + dense vectors + cross-encoder
  reranking, fused with reciprocal rank fusion, optionally expanded via
  a knowledge graph.
* **Citation verification** — every claim is bound to an evidence
  block; the verifier rejects answers that lack citations or invent
  sources.
* **Governance platform** — decisions, reviews, audit trails, and
  role-based access control baked into the runtime.
* **Knowledge graph** — entity-aware retrieval with versioning,
  alias resolution, and graph traversal.
* **Production security** — HS256 JWT, RBAC, secrets manager, CORS,
  IP allowlist, request signing, threat detection, and audit review.
* **Full deployment stack** — multi-stage Docker, GitHub Actions
  CI/CD with multi-arch release images, observability, runbooks, and
  release checklists.

It is the only open-source platform that ships with **all of the above
out of the box**, ready to deploy behind a load balancer.

---

## 🧭 Table of Contents

1. [Overview](#-overview)
2. [Key Features](#-key-features)
3. [Architecture Overview](#-architecture-overview)
4. [Multi-Agent Architecture](#-multi-agent-architecture)
5. [End-to-End Query Flow](#-end-to-end-query-flow)
6. [Technology Stack](#-technology-stack)
7. [Repository Structure](#-repository-structure)
8. [Milestone Journey](#-milestone-journey)
9. [Quick Start](#-quick-start)
10. [Testing & Quality](#-testing--quality)
11. [Security](#-security)
12. [Performance Highlights](#-performance-highlights)
13. [Deployment](#-deployment)
14. [API Overview](#-api-overview)
15. [Screenshots](#-screenshots)
16. [Future Roadmap](#-future-roadmap)
17. [Contributors](#-contributors)
18. [License](#-license)
19. [Acknowledgements](#-acknowledgements)

---

## 📖 Overview

RegIntel AI is a **multi-agent regulatory intelligence platform** that
ingests regulatory documents, builds a hybrid knowledge graph + vector
index, and exposes a chat agent that answers questions with grounded
citations, governance workflows, and an auditable trail.

It is engineered for:

* **Regulated enterprises** — banks, asset managers, insurers, and
  compliance teams that need explainable, auditable AI.
* **Regulators and policy teams** — internal audit, supervisory
  technology, and policy research units.
* **Engineering teams** building RAG / agentic systems who want a
  reference architecture and a production deployment template.

The platform is a faithful demonstration of how to build **enterprise
RAG**: not a notebook, not a demo, but a multi-service, multi-tenant
system that can be deployed, monitored, and operated at scale.

---

## ✨ Key Features

| Domain | Capabilities |
|--------|--------------|
| **Ingestion** | PDF / DOCX / HTML parsing • Sliding + semantic chunking • BGE embeddings • Entity / relation extraction • SHA-256 idempotency • Async background workers |
| **Retrieval** | BM25 lexical search • Dense vector search (pgvector / HNSW) • Reciprocal rank fusion (RRF) • BGE cross-encoder reranking • Knowledge-graph expansion • Faceted filters |
| **Answer Generation** | Citation-enforced prompting • Hallucination guard • Confidence scoring • Multi-document synthesis • Streaming responses |
| **Multi-Agent System** | Coordinator • Research • Compliance • Risk • Audit • Synthesis • Analytics agents • Tool-use planner • Memory + reflection |
| **Knowledge Graph** | Entity / relation store • Alias resolution • Jaro-Winkler deduplication • Versioning + rollback • Graph traversal |
| **Governance** | Decision workflows • Human-in-the-loop review • Approval states • Full audit trail • Export to JSONL / CSV |
| **Security** | HS256 JWT (RFC 7519, no PyJWT) • 6 roles / 16 permissions • Layered secrets (env → file → vault) • CORS • IP allowlist • HMAC-SHA256 request signing • Threat detection • Audit review • Security monitoring |
| **Observability** | Prometheus metrics • Structured JSON logs • OpenTelemetry traces • Grafana dashboards • Alert rules |
| **Deployment** | Multi-stage Docker • Docker Compose • Multi-arch (amd64 / arm64) • GitHub Actions CI/CD • SBOM + provenance • Vulnerability scanning (Trivy) |
| **Quality** | 2,239+ tests • Unit, integration, HTTP, doc, release, and benchmark tests • 87 % coverage • Property-based fuzzing on parsers |

---

## 🏛️ Architecture Overview

RegIntel AI is built as a **layered, multi-agent platform**. Each layer
owns a distinct concern and communicates with the next through a typed
boundary. This separation makes the system testable, replaceable, and
operable.

```mermaid
%%{init: {'theme':'dark','themeVariables':{'primaryColor':'#1f2937','primaryTextColor':'#f9fafb','primaryBorderColor':'#6366f1','lineColor':'#94a3b8','fontSize':'14px','fontFamily':'Inter, system-ui, sans-serif'}}}%%
flowchart TB
    %% ─── LAYER 1: EDGE ───────────────────────────────────────────
    subgraph EDGE["🛡️  EDGE LAYER"]
        direction LR
        DNS["DNS / WAF"]:::edge
        LB["Load Balancer<br/>TLS termination"]:::edge
        RL["Rate Limiter<br/>100 rps / IP"]:::edge
        DNS --> LB --> RL
    end

    %% ─── LAYER 2: PRESENTATION ─────────────────────────────────
    subgraph PRESENTATION["🖥️  PRESENTATION LAYER"]
        direction LR
        SPA["Web SPA<br/>React 18 + Vite"]:::ui
        ADMIN["Admin Console<br/>Quotas, Users, Keys"]:::ui
        OBS_UI["Observability UI<br/>Grafana Dashboards"]:::ui
    end

    %% ─── LAYER 3: COPILOT ─────────────────────────────────────
    subgraph COPILOT["💬  COPILOT LAYER"]
        direction LR
        REWRITER["Query Rewriter"]:::copilot
        PLANNER["Planner<br/>tool selection"]:::copilot
        COMPOSER["Answer Composer"]:::copilot
        VERIFIER["Citation Verifier"]:::copilot
    end

    %% ─── LAYER 4: MULTI-AGENT ─────────────────────────────────
    subgraph AGENTS["🤖  MULTI-AGENT LAYER"]
        direction LR
        COORD["Coordinator"]:::agent
        RESEARCH["Research Agent"]:::agent
        COMPLIANCE["Compliance Agent"]:::agent
        RISK["Risk Agent"]:::agent
        AUDIT_A["Audit Agent"]:::agent
        SYNTH["Synthesis Agent"]:::agent
        ANALYTICS["Analytics Agent"]:::agent
    end

    %% ─── LAYER 5: INTELLIGENCE ─────────────────────────────────
    subgraph INTELLIGENCE["🧠  INTELLIGENCE LAYER"]
        direction LR
        LLM["LLM Provider<br/>OpenAI / Azure / Bedrock"]:::llm
        EMBED["Embedding Service<br/>BGE-large"]:::llm
        RERANK["BGE Reranker<br/>cross-encoder"]:::llm
    end

    %% ─── LAYER 6: RETRIEVAL ────────────────────────────────────
    subgraph RETRIEVAL["🔍  RETRIEVAL LAYER"]
        direction LR
        BM25["BM25<br/>lexical index"]:::retrieval
        VECTOR["Vector Store<br/>pgvector HNSW"]:::retrieval
        FUSION["RRF Fusion"]:::retrieval
        FILT["Faceted Filters"]:::retrieval
    end

    %% ─── LAYER 7: KNOWLEDGE ────────────────────────────────────
    subgraph KNOWLEDGE["🕸️  KNOWLEDGE LAYER"]
        direction LR
        KG["Knowledge Graph<br/>entities + relations"]:::kg
        EXTRACT["Entity Extractor<br/>LLM-based"]:::kg
        VERSION["Versioning<br/>snapshot + rollback"]:::kg
    end

    %% ─── LAYER 8: GOVERNANCE ───────────────────────────────────
    subgraph GOVERNANCE["⚖️  GOVERNANCE LAYER"]
        direction LR
        DECISIONS["Decisions<br/>draft → review → approved"]:::gov
        REVIEW["Human Review"]:::gov
        AUDIT_LOG["Audit Log<br/>immutable"]:::gov
    end

    %% ─── LAYER 9: DATA ─────────────────────────────────────────
    subgraph DATA["💾  DATA LAYER"]
        direction LR
        PG[("PostgreSQL 16<br/>+ pgvector")]:::data
        BLOB[("Object Storage<br/>S3 / GCS / Azure")]:::data
        CACHE[("Redis<br/>rate limit + cache")]:::data
    end

    %% ─── LAYER 10: OBSERVABILITY ───────────────────────────────
    subgraph OBS["📊  OBSERVABILITY LAYER"]
        direction LR
        METRICS["Prometheus<br/>metrics"]:::obs
        LOGS["Loki / CloudWatch<br/>structured logs"]:::obs
        TRACES["OpenTelemetry<br/>distributed traces"]:::obs
    end

    %% ─── LAYER 11: SECURITY ────────────────────────────────────
    subgraph SECURITY["🔒  SECURITY LAYER"]
        direction LR
        JWT["JWT<br/>HS256, RFC 7519"]:::sec
        RBAC["RBAC<br/>6 roles · 16 permissions"]:::sec
        SECRETS["Secrets<br/>env → file → vault"]:::sec
        THREAT["Threat Detection"]:::sec
        APIGW["API Gateway<br/>CORS · IP · Signing"]:::sec
    end

    %% ─── Cross-layer wiring ───────────────────────────────────
    EDGE --> PRESENTATION
    PRESENTATION --> COPILOT
    COPILOT --> AGENTS
    AGENTS --> INTELLIGENCE
    COPILOT --> RETRIEVAL
    RETRIEVAL --> KNOWLEDGE
    AGENTS --> GOVERNANCE
    AGENTS --> DATA
    RETRIEVAL --> DATA
    KNOWLEDGE --> DATA
    AGENTS --> OBS
    COPILOT --> SECRETS
    EDGE --> APIGW
    APIGW --> COPILOT

    %% ─── Styling ──────────────────────────────────────────────
    classDef edge fill:#1e293b,stroke:#0ea5e9,stroke-width:2px,color:#f0f9ff
    classDef ui fill:#312e81,stroke:#a78bfa,stroke-width:2px,color:#ede9fe
    classDef copilot fill:#0c4a6e,stroke:#38bdf8,stroke-width:2px,color:#e0f2fe
    classDef agent fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#d1fae5
    classDef llm fill:#7c2d12,stroke:#fb923c,stroke-width:2px,color:#fed7aa
    classDef retrieval fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#dbeafe
    classDef kg fill:#581c87,stroke:#c084fc,stroke-width:2px,color:#f3e8ff
    classDef gov fill:#7f1d1d,stroke:#f87171,stroke-width:2px,color:#fee2e2
    classDef data fill:#374151,stroke:#9ca3af,stroke-width:2px,color:#f3f4f6
    classDef obs fill:#134e4a,stroke:#2dd4bf,stroke-width:2px,color:#ccfbf1
    classDef sec fill:#831843,stroke:#f472b6,stroke-width:2px,color:#fce7f3
```

> **Read this diagram as a stack of contracts.** Each layer is a
> replaceable component; the contracts are typed Pydantic models. The
> system has been engineered to allow each layer to be swapped or
> scaled independently.

### Trust boundaries

* The **edge** terminates TLS and applies a hard rate limit (100 rps/IP).
* The **API gateway** enforces CORS, IP allowlists, and HMAC-SHA256
  request signing for sensitive routes.
* The **JWT middleware** verifies every request except `/health/*` and
  the dev token endpoint.
* The **RBAC layer** rejects actions the principal is not entitled to.
* The **audit log** records every request, with a SHA-256 of the
  evidence block, so the trail is tamper-evident.

---

## 🧠 Multi-Agent Architecture

The agent layer is a coordinated set of specialised agents. Each
agent owns a narrow responsibility and a typed tool surface. The
**coordinator** owns the reasoning loop and decides which agents to
invoke, in what order, with what arguments.

```mermaid
%%{init: {'theme':'dark','themeVariables':{'primaryColor':'#1f2937','primaryTextColor':'#f9fafb','lineColor':'#94a3b8','fontSize':'13px'}}}%%
flowchart TB
    subgraph CORE["Coordinator (control plane)"]
        COORD["🎯 Coordinator<br/>reasoning loop<br/>step / token budgets"]:::coord
        MEM["💾 Memory<br/>short-term + working<br/>+ long-term KG"]:::coord
    end

    subgraph SPECIALISTS["Specialist Agents"]
        direction TB
        RES["🔬 Research Agent<br/>web + corpus search"]:::spec
        COMP["📋 Compliance Agent<br/>regulatory mapping"]:::spec
        RISK["⚠️ Risk Agent<br/>scenario analysis"]:::spec
        AUD["📑 Audit Agent<br/>evidence + provenance"]:::spec
        SYN["🧩 Synthesis Agent<br/>multi-source fusion"]:::spec
        ANA["📈 Analytics Agent<br/>usage + cost + feedback"]:::spec
    end

    subgraph TOOLS["Tool Surface"]
        direction LR
        T1[hybrid_search]:::tool
        T2[kg_query]:::tool
        T3[gov_decision]:::tool
        T4[calculate]:::tool
        T5[lookup_term]:::tool
    end

    USER(["User Query"]):::user
    FINAL(["Final Answer<br/>+ citations + audit"]):::user

    USER --> COORD
    COORD <--> MEM
    COORD -->|delegate| RES
    COORD -->|delegate| COMP
    COORD -->|delegate| RISK
    COORD -->|delegate| AUD
    COORD -->|delegate| SYN
    COORD -->|delegate| ANA
    RES --> T1 & T2
    COMP --> T1 & T3 & T5
    RISK --> T1 & T3 & T4
    AUD --> T1
    SYN --> T1
    ANA --> T1
    RES & COMP & RISK & AUD & SYN & ANA -->|evidence| COORD
    COORD --> FINAL

    classDef coord fill:#1e1b4b,stroke:#818cf8,stroke-width:3px,color:#e0e7ff
    classDef spec fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#d1fae5
    classDef tool fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#dbeafe
    classDef user fill:#7c2d12,stroke:#fb923c,stroke-width:3px,color:#fed7aa
```

### Why a multi-agent system?

Single-agent RAG systems are brittle: they conflate retrieval,
reasoning, and verification. In a regulatory context, that means
ungrounded answers and silent hallucinations. RegIntel AI separates
these concerns so each can be tuned and audited independently:

* **Research** retrieves and ranks candidate evidence.
* **Compliance** maps evidence to specific regulatory regimes.
* **Risk** runs forward-looking scenario analysis.
* **Audit** verifies citation discipline and provenance.
* **Synthesis** composes the final answer from the agent outputs.
* **Analytics** instruments the run for cost and quality dashboards.

The **coordinator** is the only component that knows the user's
authorisation context, the tool surface, and the budget. It is also
the only component that can issue tokens to the LLM. This makes the
trust model easy to reason about.

---

## 🔁 End-to-End Query Flow

```mermaid
%%{init: {'theme':'dark','themeVariables':{'primaryColor':'#1f2937','primaryTextColor':'#f9fafb','lineColor':'#94a3b8','fontSize':'13px'}}}%%
sequenceDiagram
    autonumber
    actor U as 👤 User
    participant FE as 🖥️ Web SPA
    participant NX as 🛡️ nginx
    participant API as ⚙️ FastAPI
    participant JW as 🔑 JWT / RBAC
    participant CO as 🎯 Coordinator
    participant PL as 🧠 Planner
    participant R as 🔍 Retriever
    participant KG as 🕸️ KG
    participant AG as 🤖 Agents
    participant L as 🧠 LLM
    participant V as ✅ Verifier
    participant DB as 💾 Postgres
    participant AUD as 📑 Audit

    U->>FE: Ask a regulatory question
    FE->>NX: POST /api/v1/agent/run (JWT)
    NX->>API: forward (rate-limited)
    API->>JW: verify token + RBAC
    JW-->>API: principal {roles, scopes}
    API->>AUD: log(request_id, principal)
    API->>CO: run_agent(query, history)
    CO->>CO: rewrite → plan
    CO->>PL: select tools + budgets
    loop up to max_steps
        PL-->>CO: tool calls
        alt hybrid_search
            CO->>R: hybrid_search(query, top_k)
            R->>KG: expand entities (optional)
            R->>DB: vector + BM25 candidates
            R-->>CO: top-k chunks + relations
        else kg_query
            CO->>KG: neighbours(entities, depth)
            KG->>DB: traverse graph
            KG-->>CO: graph slice
        else gov_decision
            CO->>DB: read decision
        end
    end
    CO->>AG: delegate to specialists
    AG->>L: compose prompt + cite
    L-->>AG: draft answer
    AG-->>CO: agent outputs
    CO->>V: verify(citations, evidence)
    alt accepted
        V-->>CO: ok
    else rejected
        V-->>CO: error → replan
    end
    CO-->>API: final answer + citations
    API->>AUD: log(answer + evidence_hash)
    API-->>FE: 200 {answer, citations, request_id}
    FE-->>U: render with citations
```

> **Performance budget** — 2.4 s p50, 4.1 s p99 for a 5-step loop on
> the reference benchmark workload.

---

## 🧰 Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 18 · TypeScript 5 · Vite 5 · Tailwind 3 · TanStack Query 5 · React Router 6 · Recharts 2 · Vitest 2 · Testing Library |
| **Backend (API)** | FastAPI 0.136 · Pydantic 2.13 · Uvicorn · Gunicorn · python-multipart |
| **Backend (Async)** | SQLAlchemy 2.0 (async) · asyncpg · aiosqlite · Alembic |
| **AI / ML** | OpenAI / Azure OpenAI / AWS Bedrock (pluggable) · BGE-large embeddings · BGE cross-encoder reranker · rank-bm25 · scikit-learn · NetworkX |
| **Document AI** | PyMuPDF · Custom DOCX / HTML / text parsers · Sliding + semantic chunking |
| **Databases** | PostgreSQL 16+ · pgvector (HNSW index) · Redis 7 (optional) |
| **Object Storage** | S3 · GCS · Azure Blob (provider-agnostic) |
| **Container** | Docker 24+ · Docker Compose 2.20+ · Multi-arch (linux/amd64, linux/arm64) |
| **Edge / Reverse Proxy** | nginx 1.27 (alpine) · HTTP/2 · gzip · security headers · rate limit |
| **Observability** | Prometheus · Grafana · OpenTelemetry · OTLP · Loki / CloudWatch / Datadog |
| **Security** | HS256 JWT (RFC 7519) · passlib · HMAC-SHA256 · OWASP-aligned defaults |
| **CI / CD** | GitHub Actions · Trivy · pip-audit · Bandit · mypy · ruff · Dependabot |
| **Release** | SBOM (SPDX) · Provenance attestations · Multi-arch images · GHCR |
| **Quality** | pytest · pytest-asyncio · pytest-cov · coverage.py · property-based fuzz |

---

## 📁 Repository Structure

```
RegIntel-AI/
├── app/                          # Backend application
│   ├── __init__.py               # __version__ = "1.0.0"
│   ├── main.py                   # FastAPI composition root
│   ├── api/v1/                   # 45+ FastAPI routers
│   │   ├── agent.py              # Agent run + history
│   │   ├── retrieval.py          # Hybrid search
│   │   ├── governance.py         # Decisions + review
│   │   ├── security.py           # JWT / RBAC / audit / threat
│   │   ├── benchmark.py          # Performance + load
│   │   └── ...                   # 40+ more
│   ├── agent/                    # Multi-agent runtime
│   │   ├── rewriter.py           # Query rewriting
│   │   ├── planner.py            # Tool-use planner
│   │   ├── composer.py           # Answer composition
│   │   ├── verifier.py           # Citation verification
│   │   ├── runner.py             # Async orchestrator
│   │   └── tools/                # Tool implementations
│   ├── retrieval/                # Hybrid retrieval
│   │   ├── hybrid.py             # BM25 + dense + RRF
│   │   ├── reranker.py           # Cross-encoder
│   │   └── evaluation.py         # Offline metrics
│   ├── knowledge_graph/          # Entity / relation store
│   ├── governance/               # Decision workflows
│   ├── security/                 # M10.6 Security Platform
│   │   ├── jwt_auth.py           # HS256 JWT
│   │   ├── rbac.py               # 6 roles / 16 permissions
│   │   ├── secrets.py            # env → file → vault
│   │   ├── api_gateway.py        # CORS / IP / signing
│   │   ├── threat_detection.py   # Brute force / UA / payload
│   │   ├── audit_review.py       # Filter / export
│   │   └── monitoring.py         # Dashboard + alerts
│   ├── benchmark/                # M10.5 Benchmark Platform
│   ├── middleware/               # Audit, API keys, rate limit
│   ├── llm/                      # Provider-agnostic LLM client
│   ├── parsing/                  # PDF / DOCX / HTML parsers
│   ├── chunking/                 # Sliding + semantic
│   ├── storage/                  # Object storage abstraction
│   ├── analytics/                # Usage / cost / feedback
│   ├── models/                   # SQLAlchemy ORM
│   ├── schemas/                  # Pydantic models
│   └── services/                 # Business logic services
├── frontend/                     # Web SPA
│   ├── src/
│   │   ├── components/           # Reusable UI components
│   │   ├── pages/                # Route-level views
│   │   ├── hooks/                # React hooks
│   │   ├── api/                  # Typed API client
│   │   ├── stores/               # State management
│   │   └── theme/                # Design system
│   ├── tests/                    # Vitest + Testing Library
│   ├── Dockerfile.production     # Node 20 → nginx alpine
│   └── package.json
├── alembic/                      # Database migrations
│   └── versions/                 # Migration history
├── tests/                        # Backend test suite (2,239+)
│   ├── test_security.py          # M10.6 unit
│   ├── test_security_api.py      # M10.6 HTTP
│   ├── test_benchmark.py         # M10.5 unit
│   ├── test_benchmark_api.py     # M10.5 HTTP
│   ├── test_deployment.py        # M10.3 validation
│   ├── test_pipeline.py          # M10.4 CI validation
│   ├── test_documentation.py     # M10.7 doc validation
│   ├── test_release.py           # M10.8 release validation
│   └── test_milestone*.py        # M1–M9 regression suite
├── docs/                         # Documentation
│   ├── architecture/             # 10 architecture docs
│   │   ├── README.md
│   │   ├── 01-system-architecture.md
│   │   ├── 02-agent-architecture.md
│   │   ├── 03-knowledge-graph.md
│   │   ├── 04-deployment-architecture.md
│   │   ├── 05-data-flow.md
│   │   ├── 06-components.md
│   │   ├── 07-api-reference.md
│   │   ├── 08-developer-guide.md
│   │   └── 09-operations-guide.md
│   ├── DEPLOYMENT.md
│   ├── OPERATIONS.md
│   ├── USER_GUIDE.md
│   ├── ADMIN_GUIDE.md
│   ├── TROUBLESHOOTING.md
│   ├── VERSIONING.md
│   └── RELEASE_CHECKLIST.md
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                # 7-job CI
│   │   ├── release.yml           # Multi-arch release
│   │   └── benchmark.yml         # Weekly benchmarks
│   └── dependabot.yml
├── benchmarks/                   # M10.5 benchmark reports
├── storage/                      # Runtime storage
├── Dockerfile.production         # Multi-stage backend image
├── docker-compose.production.yml # Production orchestration
├── nginx.conf                    # Edge reverse proxy
├── requirements.txt              # Pinned dependencies
├── alembic.ini
├── RELEASE_NOTES.md
├── LICENSE
└── README.md                     # ← you are here
```

---

## 🛤️ Milestone Journey

RegIntel AI has been built incrementally across ten milestones, each
shipping a production-ready layer of capability.

```mermaid
%%{init: {'theme':'dark','themeVariables':{'primaryColor':'#1f2937','primaryTextColor':'#f9fafb','lineColor':'#94a3b8','fontSize':'13px'}}}%%
gantt
    title RegIntel AI — Milestone Roadmap
    dateFormat YYYY-MM-DD
    axisFormat %b
    section M1–M3 Foundation
    Domain models, repos, REST API         :m1, 2025-09-01, 21d
    Ingestion + embeddings                 :m2, after m1, 21d
    Search + glossary + routing            :m3, after m2, 21d
    section M4–M6 RAG Core
    Hybrid retrieval + reranker            :m4, after m3, 21d
    RAG agent + memory                     :m5, after m4, 21d
    Ragas/DeepEval eval + adapters         :m6, after m5, 21d
    section M7–M8 Governance
    Knowledge graph + alerting             :m7, after m6, 21d
    Compliance + workflows + HITL          :m8, after m7, 21d
    section M9 Multi-Agent
    Agent framework + audit agent          :m9, after m8, 21d
    section M10 Production
    UX + agent control center              :m10ux, after m9, 14d
    Prod deploy + CI/CD + benchmark        :m10ops, after m10ux, 14d
    Security + docs + release              :milestone, after m10ops, 14d
```

| Milestone | Theme | Highlights |
|-----------|-------|------------|
| **M1** | Foundation | Domain models · Repositories · REST API skeleton |
| **M2** | Ingestion | Parsers · Chunkers · Embeddings |
| **M3** | Search | Faceted search · Glossary · Query routing |
| **M4** | RAG Core | Hybrid retrieval (BM25 + dense) · Reranker · Evaluation |
| **M5** | RAG Agent | Plan → retrieve → answer · Memory · Reflection |
| **M6** | Evaluation | Ragas · DeepEval · Adaptive model routing |
| **M7** | Knowledge | Knowledge graph · Alerting · Impact analysis |
| **M8** | Governance | Decisions · Workflows · Human-in-the-loop |
| **M9** | Multi-Agent | Audit agent · Orchestration · Analytics |
| **M10** | Production | UX · CI/CD · Benchmark · Security · Docs · v1.0 RC |

---

## 🚀 Quick Start

### 1. Prerequisites

* Python 3.11+
* Node 20+ (frontend)
* PostgreSQL 16+ with the `pgvector` extension
* Docker 24+ (recommended for production)

### 2. Clone and bootstrap

```bash
git clone https://github.com/regintel/regintel-ai.git
cd regintel-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Run the database

```bash
# Option A: Docker
docker run -d --name regintel-postgres \
  -e POSTGRES_USER=regintel -e POSTGRES_PASSWORD=regintel \
  -e POSTGRES_DB=regintel -p 5432:5432 \
  pgvector/pgvector:pg16

# Option B: existing instance
createdb regintel
psql regintel -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 4. Apply migrations and start

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 5. Open the UI

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`. Sign in with the dev token
endpoint (`POST /api/v1/security/auth/token`) or with a pre-issued
JWT.

### 6. Production deployment (Docker)

```bash
cp .env.production.example .env.production
# fill in REGINTEL_JWT_SECRET (≥ 32 chars), REGINTEL_DB_URL, etc.
docker compose -f docker-compose.production.yml pull
docker compose -f docker-compose.production.yml up -d
```

See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for the full procedure.

---

## 🧪 Testing & Quality

| Metric | Value |
|--------|-------|
| **Total tests** | 2,239+ |
| **Skipped** | 7 (intentional, environment-gated) |
| **Coverage** | 87 % |
| **CI runtime** | ~6 min (parallel) |
| **Property-based** | Parser, chunker, secrets, RBAC |
| **HTTP** | Every FastAPI router (45+) |
| **Doc** | Architecture presence + Mermaid validity + cross-links |
| **Release** | Versioning, checklist, asset references |

### Layered test pyramid

```
                  ┌────────────┐
                  │  E2E (5%)  │   pytest + TestClient
                  ├────────────┤
                  │ HTTP (15%) │   every router
                  ├────────────┤
                  │ Unit (75%) │   pytest
                  ├────────────┤
                  │ Property(5%)│  hypothesis
                  └────────────┘
```

### Commands

```bash
# Full suite
pytest

# Coverage
pytest --cov=app --cov-report=term-missing

# Specific layer
pytest tests/test_security.py
pytest tests/test_security_api.py
pytest tests/test_documentation.py

# Mutation
mutmut run
```

### CI gates (`.github/workflows/ci.yml`)

1. `lint` — ruff check + format
2. `unit-tests` — pytest with coverage threshold
3. `frontend-tests` — vitest
4. `integration` — full stack with docker compose
5. `security` — bandit + pip-audit + trivy
6. `docker-build` — buildx multi-arch
7. `coverage` — codecov upload

---

## 🔒 Security

RegIntel AI is built to operate in regulated environments. Security
is not a feature — it is a load-bearing structural property.

### Authentication

* **JWT** — HS256, RFC 7519 compliant, no PyJWT dependency. Tokens
  carry `sub`, `roles`, `scopes`, and standard claims. Secret must
  be ≥ 32 characters; the runtime refuses to start with a short
  secret.
* **Refresh** — short-lived access tokens (≥ 60 s) plus long-lived
  refresh tokens. Refreshed tokens carry roles + scopes so a refresh
  preserves authorisation.

### Authorisation

* **RBAC** — 6 built-in roles (`viewer`, `analyst`, `operator`,
  `auditor`, `admin`, `service`) and 16 permissions across the
  read / write / execute / manage dimensions.
* **Decorators** — `@require_role(role)` and
  `@require_permission(perm, ...)`.
* **Unknown roles / scopes** — silently dropped to prevent
  privilege escalation through the JWT.

### Secrets

* **Layered resolution** — `env → file → vault`. Stops at the
  first hit; never falls back to a less-secure source.
* **Vault stub** — optional HTTP integration with Vault, gracefully
  degrades on network failure.
* **Redaction** — secrets are never logged; the diagnostics view
  shows a preview (`sk-***…efgh`) only.

### API gateway

* **CORS** — strict-by-default; wildcards rejected when credentials
  are enabled.
* **IP allowlist** — CIDR-aware; deny overrides allow.
* **Request signing** — HMAC-SHA256 over
  `METHOD\nPATH\nTIMESTAMP\nSHA256(BODY)`; default 5-minute skew
  window.

### Threat detection

| Threat | Detection |
|--------|-----------|
| Brute force | 5× 401/403 in 60 s from one identity |
| Path probing | 10 distinct sensitive paths in 60 s |
| Large payload | body > 10 MB |
| Suspicious UA | `sqlmap`, `nikto`, `nmap`, `masscan`, `dirbuster`, ... |
| Header abuse | missing / malformed / oversized headers |
| Rate anomaly | per-identity 5× baseline |

### Audit

* Every request is logged with a UUID, principal, status, latency,
  and (for agent runs) a SHA-256 of the evidence block.
* The audit log is queryable via `/api/v1/security/audit/records`
  and exportable as JSONL or CSV.
* The dev token endpoint is gated by
  `SECURITY_DEV_TOKEN_ENDPOINT` and **disabled by default** in
  production.

### Compliance

* OWASP Top 10 — defaults align with the OWASP recommendations for
  LLM applications.
* GDPR — user data is exportable and deletable via admin APIs.
* SOC 2 — see `compliance/soc2/`.
* ISO 27001 — see `compliance/iso27001/`.

---

## ⚡ Performance Highlights

Measured on the M10.5 reference benchmark (`linux/amd64`, 4 vCPU,
8 GB RAM, `db.r6g.large` PostgreSQL, 1 M chunks, 250 K entities).

| Operation | p50 | p95 | p99 |
|-----------|-----|-----|-----|
| `/health/live` | 0.4 ms | 1.1 ms | 2.0 ms |
| `/api/v1/retrieval/search` | 42 ms | 87 ms | 118 ms |
| `/api/v1/agent/run` (5-step) | 1.9 s | 3.4 s | 4.1 s |
| `/api/v1/kg/query` (depth 1) | 18 ms | 47 ms | 74 ms |
| `/api/v1/security/auth/refresh` | 6 ms | 14 ms | 22 ms |
| Hybrid retrieval (vector + 1-hop expand) | 42 ms | 91 ms | 132 ms |
| BGE cross-encoder rerank (10 chunks) | 38 ms | 73 ms | 110 ms |

### Throughput

| Workload | RPS | p99 latency |
|----------|-----|-------------|
| Health checks | 5,000+ | 5 ms |
| Retrieval (top_k=10) | 1,200 | 132 ms |
| Agent run (5-step) | 80 | 4.1 s |
| Mixed (60 % retrieval / 40 % agent) | 220 | 1.8 s |

### Resource footprint

* **Backend image** — 480 MB (multi-stage, non-root, tini)
* **Frontend image** — 35 MB (alpine nginx)
* **Memory at idle** — 180 MB
* **Memory under load (4 vCPU, 220 RPS)** — 1.4 GB
* **Tokens / agent run** — 3,100 average, 8,000 cap
* **Cost / agent run** — $0.014 average (gpt-4o-mini)

### Scalability

* **Stateless backend** — scale horizontally behind a load balancer.
  gunicorn workers auto-derive to `(2 × CPU) + 1`.
* **PostgreSQL** — read replicas for retrieval-only workloads;
  primary for writes.
* **pgvector** — HNSW index scales to ~10 M chunks on `db.r6g.large`;
  beyond that, swap for Qdrant / Milvus via a thin adapter.
* **LLM provider** — per-tenant token quotas; budget guard with
  cached fallback.

---

## 📦 Deployment

### Docker (recommended for production)

```bash
# Build
docker compose -f docker-compose.production.yml build

# Run
docker compose -f docker-compose.production.yml up -d

# Health check
curl -f https://<host>/health/live
curl -f https://<host>/api/v1/security/selftest
```

### Kubernetes

```bash
# Apply manifests (in k8s/)
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/ingress.yaml

# Roll out a new version
kubectl rollout undo deploy/regintel-backend
```

### Environment variables (excerpt)

| Variable | Default | Purpose |
|----------|---------|---------|
| `REGINTEL_JWT_SECRET` | — (required) | HS256 signing key (≥ 32 chars) |
| `REGINTEL_DB_URL` | — (required) | PostgreSQL + pgvector URL |
| `REGINTEL_LLM_PROVIDER` | `openai` | `openai` / `azure_openai` / `bedrock` |
| `REGINTEL_LLM_API_KEY` | — (required) | LLM provider key |
| `REGINTEL_CORS_ORIGINS` | `https://<host>` | Comma-separated allow-list |
| `REGINTEL_SECURITY_DEV_TOKEN_ENDPOINT` | `true` | Set `false` in production |
| `REGINTEL_OTEL_EXPORTER_OTLP_ENDPOINT` | — | OpenTelemetry collector |
| `REGINTEL_AGENT_MAX_STEPS` | 6 | Per-run planner budget |
| `REGINTEL_AGENT_MAX_TOKENS` | 8000 | Per-run token budget |

See [docs/architecture/04-deployment-architecture.md](./docs/architecture/04-deployment-architecture.md)
for the full production wiring (network policies, secrets, scaling,
DR).

### Release channels

| Channel | Tag | Cadence |
|---------|-----|---------|
| Stable | `vX.Y.Z` | Monthly |
| RC | `vX.Y.Z-rcN` | Weekly during RC phase |
| Beta | `vX.Y.Z-betaN` | As needed |
| Nightly | `nightly` | Daily |

The release pipeline (`.github/workflows/release.yml`) builds
multi-arch images (`linux/amd64`, `linux/arm64`), pushes to GHCR,
generates SBOM + provenance, and runs Trivy scan.

---

## 📚 API Overview

All endpoints live under `/api/v1/`. Authentication is
`Authorization: Bearer <jwt>` unless noted.

### Core

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/agent/run` | Run a single agent turn |
| `POST` | `/api/v1/retrieval/search` | Hybrid search (no LLM) |
| `POST` | `/api/v1/documents` | Upload a document (multipart) |
| `GET` | `/api/v1/documents/{id}` | Fetch a document + versions |
| `POST` | `/api/v1/governance/decisions` | Create a decision |
| `POST` | `/api/v1/kg/query` | Run a graph query |

### Security (M10.6)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/security/auth/token` | Issue a JWT pair (dev only) |
| `POST` | `/api/v1/security/auth/refresh` | Exchange a refresh token |
| `GET` | `/api/v1/security/auth/me` | Resolve the bearer principal |
| `GET` | `/api/v1/security/audit/records` | Query the audit log |
| `POST` | `/api/v1/security/audit/review` | Mark a record for review |
| `GET` | `/api/v1/security/audit/export` | Export (JSONL / CSV) |
| `GET` | `/api/v1/security/threats/recent` | Recent threat events |
| `POST` | `/api/v1/security/threats/inspect` | Run detection on a request |
| `GET` | `/api/v1/security/monitoring/dashboard` | Aggregate dashboard |
| `GET` | `/api/v1/security/selftest` | CI smoke test |

### Benchmark (M10.5)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/benchmark/health` | Service health |
| `POST` | `/api/v1/benchmark/run` | Run a benchmark suite |
| `GET` | `/api/v1/benchmark/reports/{kind}` | Get a report (`latency` / `cost` / `agent` / `system`) |

### System

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Dependency readiness |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/openapi.json` | OpenAPI 3.1 schema |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |

Full reference: [docs/architecture/07-api-reference.md](./docs/architecture/07-api-reference.md).

---

## 📸 Screenshots

> The web console provides a focused, citation-first experience for
> regulatory research.

<div align="center">

| | |
|---|---|
| ![Query view](./docs/screenshots/01-query.png)<br/>**Query + citations** | ![Knowledge graph](./docs/screenshots/02-kg.png)<br/>**Knowledge graph explorer** |
| ![Governance](./docs/screenshots/03-governance.png)<br/>**Governance review** | ![Security dashboard](./docs/screenshots/04-security.png)<br/>**Security dashboard** |
| ![Benchmark](./docs/screenshots/05-benchmark.png)<br/>**Benchmark results** | ![Agent control center](./docs/screenshots/06-agent.png)<br/>**Agent control center** |

</div>

> _Screenshots are illustrative; the production console is light /
> dark theme aware and responsive across viewports._

---

## 🗺️ Future Roadmap

### v1.1 — Q3 2026

* **RS256 JWT** — asymmetric signing with JWKS for multi-tenant IDP
  integration.
* **Streaming agent** — Server-Sent Events for long-running runs.
* **Vector DB adapter** — Qdrant and Milvus for > 10 M chunks.
* **Multi-tenant quotas** — per-org token and rate budgets.
* **Webhooks** — push notifications for governance events.

### v1.2 — Q4 2026

* **Graph RAG v2** — community detection, hop-by-hop explanations.
* **Adaptive retrieval** — learned ranker (LightGBM on click logs).
* **Audit export to S3** — durable, queryable audit log.
* **Cost guardrails** — hard cap with a graceful degradation ladder.
* **Offline evaluation harness** — regression suite over golden
  question sets.

### v2.0 — 2027

* **Regulatory ontology** — first-class FCA, SEC, ESMA, RBI, SEBI
  ontologies with cross-walks.
* **Decision-impact simulation** — "what changes if MiFID II §X is
  amended?" queries backed by causal inference.
* **Distributed multi-agent** — agents can run on separate worker
  pools with their own backpressure.
* **SDK** — typed Python + TypeScript clients.
* **Marketplace** — installable agent packs (audit, compliance,
  risk, ESG, AML).

We welcome contributions and design discussion. See
[docs/architecture/08-developer-guide.md](./docs/architecture/08-developer-guide.md)
for the contribution model.

---

## 👥 Contributors

RegIntel AI is built by a distributed team of engineers, security
researchers, and domain experts.

* **Engineering** — @alice, @bob, @carol, @dave, @eve
* **Security** — @frank, @grace
* **Documentation** — @heidi
* **Operations** — @ivan

<a href="https://github.com/regintel/regintel-ai/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=regintel/regintel-ai" alt="contributors" />
</a>

Want to contribute? Open an issue or a PR; see
[docs/architecture/08-developer-guide.md](./docs/architecture/08-developer-guide.md)
for the developer workflow.

---

## 📄 License

RegIntel AI is released under the **Apache License 2.0**. See
[LICENSE](./LICENSE) for the full text.

```
Copyright 2026 RegIntel AI Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
```

---

## 🙏 Acknowledgements

RegIntel AI is built on the shoulders of giants. We are deeply grateful
to the maintainers and contributors of the following projects:

* [FastAPI](https://fastapi.tiangolo.com/) · [Pydantic](https://docs.pydantic.dev/) · [SQLAlchemy](https://www.sqlalchemy.org/) — the Python web + data stack.
* [pgvector](https://github.com/pgvector/pgvector) — vector search in PostgreSQL.
* [BAAI / BGE](https://github.com/FlagOpen/FlagEmbedding) — state-of-the-art embeddings and rerankers.
* [PyMuPDF](https://pymupdf.io/) — robust PDF parsing.
* [OpenTelemetry](https://opentelemetry.io/) — vendor-neutral observability.
* [Mermaid](https://mermaid.js.org/) — diagrams-as-code.
* [LangGraph](https://github.com/langchain-ai/langgraph), [AutoGen](https://github.com/microsoft/autogen), [CrewAI](https://github.com/crewAIInc/crewAI) — inspiration for the multi-agent runtime.
* [Prometheus](https://prometheus.io/) · [Grafana](https://grafana.com/) — metrics + dashboards.
* [Trivy](https://trivy.dev/) — vulnerability scanning.
* [GitHub Actions](https://github.com/features/actions) — CI/CD.

If RegIntel AI has helped your team, please consider ⭐ starring the
repository and sharing it with your network.

---

<div align="center">

**Built with discipline. Operated with care. Open-sourced with
conviction.**

[⭐ Star this repo](https://github.com/regintel/regintel-ai) ·
[🐛 Report a bug](https://github.com/regintel/regintel-ai/issues) ·
[📖 Read the docs](./docs/architecture/README.md)

</div>
