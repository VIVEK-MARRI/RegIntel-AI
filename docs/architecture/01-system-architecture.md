# 01 — System Architecture

## Overview

RegIntel AI is a retrieval-augmented regulatory intelligence platform. It
ingests regulatory documents, builds a hybrid knowledge graph + vector
index, and exposes a chat agent that answers questions with grounded
citations, governance workflows, and an auditable trail.

The system has three runtime layers:

1. **Edge** — nginx reverse proxy that terminates TLS, applies rate limits
   and security headers, and fronts the frontend SPA.
2. **Application** — a FastAPI backend that owns the API surface, the
   agent runtime, the retrieval pipeline, the knowledge graph, and the
   governance workflow engine.
3. **Data** — PostgreSQL (with the pgvector extension) for relational and
   vector storage; Redis (optional) for rate limiting and ephemeral state;
   the local filesystem for raw document blobs and audit JSONL archives.

## High-level diagram

```mermaid
flowchart LR
    classDef edge fill:#cfe2ff,stroke:#0d6efd
    classDef app fill:#d1e7dd,stroke:#198754
    classDef data fill:#fff3cd,stroke:#ffc107
    classDef sec fill:#f8d7da,stroke:#dc3545

    User([User / Client]):::edge
    Browser[Web SPA<br/>React + Vite]:::edge
    Nginx[nginx<br/>reverse proxy]:::edge
    API[FastAPI backend<br/>app.main:app]:::app
    Agent[Agent runtime<br/>app.agent]:::app
    Retrieval[Retrieval pipeline<br/>app.retrieval]:::app
    KG[Knowledge graph<br/>app.knowledge_graph]:::app
    Gov[Governance workflows<br/>app.governance]:::app
    Sec[Security platform<br/>app.security]:::sec
    Monitor[Observability<br/>app.middleware]:::app
    PG[(PostgreSQL<br/>+ pgvector)]:::data
    Blob[(Object storage<br/>raw docs)]:::data
    LLM[LLM provider<br/>Azure OpenAI / Bedrock]:::data
    OTel[OTel collector<br/>optional]:::edge

    User --> Browser
    Browser -->|HTTPS| Nginx
    Nginx -->|/api/*| API
    API --> Agent
    API --> Retrieval
    API --> KG
    API --> Gov
    Agent --> LLM
    Retrieval --> KG
    Retrieval --> PG
    Agent --> PG
    Gov --> PG
    Sec --> API
    API --> Blob
    API --> Monitor
    Monitor --> OTel
```

## Component responsibilities

| Layer | Component | Responsibility | Source |
|-------|-----------|----------------|--------|
| Edge | `nginx` | TLS termination, gzip, security headers, rate limit | `nginx.conf` |
| Edge | Web SPA | Query / answer UI, admin console, observability dashboards | `frontend/` |
| App | `app.main` | Composition root, router registration, startup | `app/main.py` |
| App | `app.api.v1.*` | HTTP handlers (FastAPI routers) | `app/api/v1/` |
| App | `app.agent` | RAG agent, tools, planners, reasoning loop | `app/agent/` |
| App | `app.retrieval` | Hybrid retrieval, re-ranking, evaluation | `app/retrieval/` |
| App | `app.knowledge_graph` | Entity/relation extraction, graph traversal | `app/knowledge_graph/` |
| App | `app.governance` | Decision review, approval workflow, audit | `app/governance/` |
| App | `app.security` | JWT, RBAC, secrets, threat detection, audit review | `app/security/` |
| App | `app.benchmark` | Performance, load, latency, cost benchmark | `app/benchmark/` |
| App | `app.middleware` | Rate limit, audit log, request ID, request signing | `app/middleware/` |
| Data | PostgreSQL | Relational + vector storage (pgvector) | `alembic/` |
| Data | Object storage | Raw PDFs, audio, video; chunked text | `app/storage/` |
| Data | LLM provider | Embeddings, completions, rerank | `app/llm/` |
| Data | OTel collector | Metrics + trace export | optional |

## Request flow (chat query)

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Web SPA
    participant NX as nginx
    participant API as FastAPI
    participant AG as Agent
    participant R as Retrieval
    participant KG as KG
    participant DB as PostgreSQL
    participant L as LLM

    U->>FE: Enter question
    FE->>NX: POST /api/v1/agent/run
    NX->>API: forward (rate-limited)
    API->>API: JWT verify + RBAC
    API->>AG: run_agent(query, principal)
    AG->>AG: rewrite + plan tools
    AG->>R: hybrid_search(query)
    R->>KG: expand entities
    R->>DB: vector + lexical
    R-->>AG: top-k chunks + entities
    AG->>L: compose prompt + ask
    L-->>AG: answer draft + citations
    AG-->>API: final answer + audit
    API-->>FE: SSE / JSON
    FE-->>U: Render answer
```

## Deployment topology

The `docker-compose.production.yml` stack runs two services:

* `backend` — single replica of the FastAPI app under gunicorn+uvicorn
  workers. Stateless — scale horizontally behind a load balancer.
* `frontend` — static SPA served by nginx. Replicas scale with traffic.

PostgreSQL and object storage are external (managed service). The stack
ships with a sidecar `otel-collector` for OTLP export (optional).

See [04 — Deployment Architecture](./04-deployment-architecture.md) for
the production wiring, network policies, and secret plumbing.

## Trust boundaries

```mermaid
flowchart TB
    classDef trust fill:#d1e7dd,stroke:#198754
    classDef dmz fill:#fff3cd,stroke:#ffc107
    classDef sec fill:#f8d7da,stroke:#dc3545

    subgraph Public[Public zone]
      Browser([User]):::dmz
    end
    subgraph DMZ[Edge zone]
      Nginx[nginx<br/>WAF, rate limit]:::dmz
    end
    subgraph App[Application zone]
      API[FastAPI]:::trust
      Agent[Agent runtime]:::trust
      DB[(PostgreSQL)]:::trust
    end
    subgraph Secrets[Secrets zone]
      Vault[(SecretsManager<br/>env → file → vault)]:::sec
    end

    Browser -->|HTTPS| Nginx
    Nginx -->|mTLS optional| API
    API --> Agent
    Agent --> DB
    API -.->|short-lived| Vault
```

Every cross-boundary call goes through authentication and authorisation
enforced by `app.security.api_gateway.APIGateway` and the JWT
middleware. See [02 — Agent Architecture](./02-agent-architecture.md)
for the inner workings of the agent and [09 — Operations
Guide](./09-operations-guide.md) for the security runbook.


## See also

* [Architecture index](./README.md)
* [01 â€” System Architecture](./01-system-architecture.md)
* [05 â€” Data Flow](./05-data-flow.md)
* [06 â€” Components](./06-components.md)
* [07 â€” API Reference](./07-api-reference.md)

