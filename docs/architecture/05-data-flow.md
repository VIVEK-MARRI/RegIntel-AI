# 05 — Data Flow

This document describes the runtime data flow for the three primary
operations: **ingest**, **search**, and **agent run**. Sequence diagrams
use the standard Mermaid notation.

## 1. Ingest pipeline

```mermaid
sequenceDiagram
    actor U as Admin
    participant API as POST /api/v1/documents
    participant P as Parser
    participant CH as Chunker
    participant EM as Embedder
    participant EX as KG Extractor
    participant DB as PostgreSQL
    participant BL as Object storage

    U->>API: upload PDF
    API->>BL: store raw blob
    API->>P: parse(pdf)
    P-->>API: text + page map
    API->>CH: chunk(text)
    CH-->>API: chunks
    API->>EM: embed(chunks)
    EM-->>API: vectors
    API->>EX: extract(chunks)
    EX-->>API: entities + relations
    API->>DB: insert chunks, entities, relations
    API-->>U: 201 {document_id, version}
```

### Notes

* Ingestion is idempotent — re-uploading the same SHA-256 is a no-op.
* The KG extractor is async; the API returns immediately and the
  extraction runs in a background task.
* The chunker is configured by `REGINTEL_CHUNK_SIZE` (default 800
  tokens) and `REGINTEL_CHUNK_OVERLAP` (default 100 tokens).

## 2. Search (hybrid retrieval)

```mermaid
sequenceDiagram
    actor U as User
    participant API as POST /api/v1/retrieval/search
    participant R as Retriever
    participant V as Vector store
    participant L as Lexical store
    participant KG as KG expander
    participant RR as Reranker
    participant DB as PostgreSQL

    U->>API: {query, top_k, expand_graph}
    API->>API: JWT verify, RBAC
    API->>R: hybrid_search(query)
    par
      R->>V: vector_search(query, top_k * 3)
      V-->>R: candidates
    and
      R->>L: lexical_search(query, top_k * 3)
      L-->>R: candidates
    end
    R->>R: reciprocal rank fusion
    alt expand_graph
      R->>KG: neighbours(entities, depth=1)
      KG->>DB: SELECT * FROM kg_relations ...
      KG-->>R: relations
    end
    R->>RR: rerank(query, candidates)
    RR-->>R: top_k
    R-->>API: chunks + entities + relations
    API-->>U: 200 {results}
```

### Notes

* Vector search uses pgvector with HNSW index.
* Lexical search uses `tsvector` (Postgres full-text) with a
  trigram index for fuzzy term matching.
* The reranker is a cross-encoder model (configurable). When the
  reranker is disabled (`REGINTEL_RETRIEVAL_RERANKER=false`),
  RRF output is returned directly.
* Each result carries a `provenance` block: `chunk_id`, `document_id`,
  `version`, `page`, `score`, `kg_relations`.

## 3. Agent run

```mermaid
sequenceDiagram
    actor U as User
    participant API as POST /api/v1/agent/run
    participant AG as Agent
    participant RW as Rewriter
    participant PL as Planner
    participant R as Retriever
    participant KG as KG
    participant L as LLM
    participant V as Verifier
    participant DB as PostgreSQL
    participant AUD as Audit log

    U->>API: {query, history}
    API->>AUD: log(request_id, principal)
    API->>AG: run_agent(query, principal)
    AG->>RW: rewrite(query)
    RW-->>AG: rewrites
    loop up to max_steps
      AG->>PL: plan(query, history, evidence)
      PL-->>AG: tool_calls
      alt tool == hybrid_search
        AG->>R: hybrid_search(...)
        R->>KG: optional expand
        R-->>AG: chunks
      else tool == kg_query
        AG->>KG: neighbours(...)
        KG-->>AG: graph
      end
    end
    AG->>L: compose_prompt(query, evidence)
    L-->>AG: draft
    AG->>V: verify(draft, evidence)
    alt verified
      V-->>AG: ok
    else rejected
      AG->>PL: replan(error)
    end
    AG-->>API: answer + citations
    API->>AUD: log(answer, evidence_hash)
    API-->>U: 200 {answer, citations, request_id}
```

### Notes

* The agent loop is bounded by `max_steps` (default 6) and
  `max_tokens` (default 8 000).
* The verifier rejects answers that lack citations or that mention
  chunks not in the evidence block.
* The audit log entry contains the principal, the evidence block
  hash, the final answer, and the token cost.

## 4. Governance decision

```mermaid
sequenceDiagram
    actor A as Analyst
    participant API as POST /api/v1/governance/decisions
    participant G as Governance service
    participant DB as PostgreSQL
    participant R as Reviewer (auditor)
    participant AUD as Audit log

    A->>API: create_decision({title, body, entities})
    API->>G: create(...)
    G->>DB: insert(decision, status=draft)
    API-->>A: 201 {decision_id}

    R->>API: review(decision_id, {approve|reject, notes})
    API->>G: review(...)
    G->>DB: update(decision, status=approved|rejected, reviewer)
    G-->>API: ok
    API->>AUD: log(review, decision_id)
    API-->>R: 200
```

### Notes

* Decisions flow through: `draft → in_review → approved | rejected`.
* The auditor role is required to call `review`.
* All transitions are immutable — the history is preserved.

## Class diagram (core domain)

```mermaid
classDiagram
    class Document {
      +id: str
      +sha256: str
      +filename: str
      +version: int
      +metadata: Dict
    }
    class Chunk {
      +id: str
      +document_id: str
      +text: str
      +page: int
      +embedding: List~float~
    }
    class Entity {
      +id: str
      +kind: EntityKind
      +canonical_name: str
    }
    class Decision {
      +id: str
      +title: str
      +status: DecisionStatus
    }
    class AgentRun {
      +id: str
      +principal: str
      +query: str
      +answer: str
      +evidence_hash: str
    }

    Document "1" --o "n" Chunk
    Chunk "n" --o "n" Entity
    Decision "n" --o "n" Entity
    AgentRun "n" --o "n" Chunk : evidence
```

## See also

* [Architecture index](./README.md)
* [01 — System Architecture](./01-system-architecture.md)
* [02 — Agent Architecture](./02-agent-architecture.md)
* [03 — Knowledge Graph](./03-knowledge-graph.md)
* [06 — Components](./06-components.md)
