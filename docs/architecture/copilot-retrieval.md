# ADR-0001: Copilot retrieval wiring (P0.0)

## Status
Accepted — 2026-07-07

## Context
The regulatory copilot (`/copilot/query`) is the primary user-facing entry point,
but `CopilotService._resolve_chunks()` never called the real retrieval pipeline.
It only used caller-supplied `chunks` (the frontend never sends them) or fell
back to `MemoryService` token-overlap search over prior Q&A history. Any new
question that had not been asked before took the `no chunks available`
degraded path and returned an empty answer.

Meanwhile `/research/run` already calls `HybridRerankPipeline.search()` and gets
real retrieved chunks, proving the pipeline works.

## Decision
`CopilotService` calls `HybridRerankPipeline.search()` **directly** for every new
`ANSWER` query whenever:
1. the caller did not supply `chunks`, and
2. memory does not contain a sufficiently relevant prior hit
   (`MEMORY_SCORE_THRESHOLD = 0.35`).

The memory path is preserved as a genuine *optimization* (skip redundant
retrieval when a near-identical question was just answered), not as the only
path. The `_empty_answer` degraded path can now only trigger when the hybrid
retriever legitimately returns zero results (e.g. no ingested documents match
the query at all).

A `retrieval_invoked` flag is attached to `OrchestratorMetadata.extra` on every
copilot response so the regression test and operators can confirm the real
pipeline ran.

## Alternatives considered
- **Shared `AnswerOrchestrationService`** used by *both* `/copilot/query` and
  `/research/run`. This would avoid duplicating retrieval-to-generation logic,
  but it is a larger refactor that touches Research, which already works. We
  chose the smaller, lower-risk fix that makes Copilot reach the same pipeline
  Research already uses. A follow-up can consolidate later if divergence appears.

## Consequences
- A brand-new question against a freshly ingested document returns a real,
  hybrid-retrieved, cited, hallucination-checked answer.
- The degraded empty-answer path is reachable only on genuine zero-result
  retrieval, never merely because memory was empty.

---

## P0.3 scope expansion: ingestion-time content screening

### Decision
Content screening (`record_screening_threat` → `screen_text` → PII + prompt-injection) that was originally scoped to the copilot query endpoint (P0.3) was expanded to run on **every chunk** at ingestion time inside `HierarchicalChunkerService.chunk_document_by_id()` (`app/services/structure/chunker.py:214`).

### Rationale
A piece of text that passes the copilot's query-level screen can still *be* an injection planted inside an ingested document. If that chunk is later retrieved into an unrelated user's prompt, the injection fires from within the trusted RAG context, making it harder to spot. Screening at ingestion catches the poison before it reaches the index.

### Consequences
- Chunker latency increases by a measured ~0.15–0.18 ms per chunk (benchmarked on 862–1016 char regulatory chunks, 500 iterations: clean-path avg 0.147 ms, flagged-path avg 0.180 ms). That is ~7–16 ms for a typical 50–100 chunk document — negligible next to embedding (~seconds) and LLM calls.
- Detections surface as `ThreatType.PROMPT_INJECTION` events, visible in the same threat-detector dashboard as copilot-level hits.
- The screen is **non-blocking**: flagged chunks are still persisted and embedded. The intent is detection and operator visibility, not denial of service against a poisoned document (the upstream caller decides how to handle a flagged document).

---

See the [Architecture README](./README.md) for the full index.
