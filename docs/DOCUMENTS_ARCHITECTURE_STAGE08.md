# Documents Architecture — STAGE 08

## 1. Product purpose

Trustworthy regulatory library: what exists, what happened on upload,
whether ingestion finished, and what is actually searchable — every
claim backed by a backend field.

## 2. Document lifecycle (frontend-visible)

```
UPLOAD accepted (POST /documents/upload → 201 {document_id, status, run_id?})
  → registry status: UPLOADED → PROCESSING → PARSING → PARSED → INDEXED
  → failure terminal: FAILED
```

Ingestion runs evolve independently through 13 states
(`pending → downloading → … → indexing → completed | failed | skipped`).
Table shows the DOCUMENT status; detail shows the latest RUN status as
`processing_status` plus backend-derived `indexed` (true iff latest run
is `completed`).

"Ready for search" is shown ONLY as `Indexed: Yes` from detail evidence.

## 3. Endpoint inventory

| Operation | Method + path | Request | Response | Notes |
|---|---|---|---|---|
| List | `GET /documents` | `source?`, `status?`, `sort_by?` (default `uploaded_at`), `sort_order?` (default `desc`), `skip?`, `limit?` (default/max 100) | BARE ARRAY (no total) | Server filters/sort/page; title search is client-side |
| Detail | `GET /documents/:id` | UUID-gated (non-UUID → 422) | `DocumentDetailResponse` (+chunk/embedding counts, `indexed`, `processing_status`) | |
| Upload | `POST /documents/upload` | multipart `file` (+optional `title/document_type/source`) | 201 `{document_id, status, run_id?}`; 400 validation; 409 duplicate | PDF/TXT only, ≤100MB (ext + MIME + size) |
| Register | `POST /documents` | — | — | Exists; UI does not use it (upload path covers creation) |
| Patch status/meta | `PATCH /documents/:id[/status]` | — | — | Exists; NOT a retry mechanism; UI does not expose it |
| Chunks | `GET /documents/:id/chunks` | — | Bare array `StoredChunkResponse` | Read-only inspector |
| Pages | `GET /documents/:id/pages` | — | Bare array `PageResponse` | Read-only inspector |
| Structure/hierarchy | `GET /documents/:id/structure\|hierarchy` | — | — | Exists; deferred (needs information-architecture design) |
| Ingestion runs | `GET /ingestion/runs` | paginated | `PaginatedIngestionRuns` | Polled while active |
| Run detail | `GET /ingestion/runs/:id` | — | `IngestionRunResponse` (incl. `failure_reason`) | Lazy-loaded for failed runs |
| Ingestion stats/scheduler | `GET /ingestion/stats\|scheduler…` | — | — | Exists; deferred to ops surfaces |
| Delete | — | — | — | DOES NOT EXIST. No delete UI by design. |
| Retry/re-ingest | — | — | — | DOES NOT EXIST. `POST /ingestion/run` needs URL/discovery, not a doc retry. No retry UI by design. |

Timestamps: ISO strings (`uploaded_at`) everywhere here.

## 4. Document list model

Server-filtered (source/status), server-sorted (uploaded_at desc ⇒ the
"recent" order is backend-justified), server-paged (25/page, Prev/Next
gated on returned length — no totals invented). Title substring search
is client-side over the fetched page and labeled as such.

## 5. Upload model

Single file per request (backend shape). Client pre-checks mirror the
server exactly: extension set `{pdf,txt}` (exact match, not substring),
100 MB cap with the server's message wording. MIME is server-enforced
(client sniffing is unreliable — documented, not duplicated). No fake
percentages: indeterminate uploading state with the filename. Success
toast states acceptance AND continued ingestion, then auto-selects the
new document so the pipeline is visible. 409 → distinct "already in
library" path.

## 6. Ingestion model

Run views via `toRunView` (id, status, terminal/failed flags, counts,
millis). Tones: completed success / failed danger / skipped neutral /
everything else info, each with a one-line plain-language explanation.

## 7. Status mapping

Document registry: UPLOADED neutral, PROCESSING/PARSING warning, PARSED
info, INDEXED success, FAILED danger. Run states: 13-value enum mapped
explicitly with an `?? status` safe fallback for unknown values. Status
is always text + color, never color-only.

## 8. Polling strategy

React Query `refetchInterval` as a DATA-DEPENDENT function (5s while any
selected scope is non-terminal, `false` otherwise) on: jobs list (any
active run), detail (selected doc non-terminal). No `setInterval`
anywhere; timers die with unmount automatically. When the polled jobs
show the selected run terminal, detail/chunks/pages invalidate once.
Chunks/pages themselves never poll (bounded inspectors + manual Refresh).

## 9. Detail model

Structured `<dl>`: status, pipeline run status, indexed Yes/No (+ honest
"searchable" qualifier), source, type, pages, chunks, embeddings,
uploaded/updated, checksum + id (truncated mono). Tabs (shared `Tabs`):
Chunks (id/section/page/tokens/content, first 20) and Pages (number +
clamped text, first 20), each with real empty states.

## 10. Chunk/page behavior

Read-only, bounded (20 + count note), scrollable, plain text (no
fake viewer chrome). Structure/hierarchy endpoints deferred.

## 11. Pagination

`skip/limit` (page size 25). No totals exist → pager shows "Page N · up
to 25" and gates Next on short pages. Never `items.length` as a total.

## 12. Filters

Source + status → server query params (page resets). Title → local
substring over the fetched page, labeled "on this page". No decorative
controls; every control changes the request or the visible set.

## 13. Mutation/invalidation matrix

| Mutation | Invalidates | Deliberately not |
|---|---|---|
| Upload success | `documentsKeys.all` (all list variants/detail/inspectors), `ingestionJobs`, `dashboardKeys.compliance()` | unrelated domains (MSW `onUnhandledRequest:error` proves it) |
| Run reaches terminal (polled) | selected `detail` + `chunks` + `pages` | list (status visible on next nav/fetch) |
| Detail Refresh | `detail` + `chunks` + `pages` | list, jobs |

## 14. Loading/error/empty states

Per-region Skeleton / ErrorState(+retry) / EmptyState with distinct copy
for empty library vs load failure vs no-chunks vs no-pages vs no-runs.
Upload errors arrive as toasts (canonical `ApiClientError`); 409 has its
own path. No stack traces; failure_reason truncated to 200 chars.

## 15. Responsive strategy

Metrics `2 → sm:4`; main/aside stack below `lg`; table scrolls via shared
`Table`; filters stack; drawer-free detail (inline panel). Verified
390/768/1024/1440, zero overflow (screenshots `landing/_review/ds8-*`).

## 16. Accessibility

Single `h1`; labeled file input + keyboard-activated Select button;
labeled selects/search; table `caption` + scoped headers; keyboard rows
(Enter/Space); status text; labelled tabs + tabpanels; dialogs: none
needed (no delete). Truncation is JS-helper based with full text in
`title` where space allows (rows keep full titles in detail view).

## 17. Security

Bearer via Stage 02 client; UUIDs path-encoded; failure text rendered
as text (never HTML); checksum/ids truncated display only; no secrets
in URLs or logs.

## 18. Backend limitations (honest)

No delete, no retry/re-ingest, no progress percent, no list totals, no
title search param, structure/hierarchy deferred, scheduler/stats
deferred, PATCH endpoints intentionally unexposed (not user retry).

## 19. Deferred features

Multi-file batch upload, title/source metadata on upload, server title
search, structure/hierarchy inspector, ingestion stats surface, run
detail history, virtualized tables (Stage 17 if needed).

```mermaid
User
 |
 v
DocumentsPage
 |
 +---- Upload ──> POST /documents/upload ──> select new doc
 |       |                                    |
 |       v                                    v
 |   indeterminate state              detail/chunks/pages queries
 |       |
 |       v
 |   invalidate: documents.* + ingestion jobs + dashboard compliance
 |
 +---- Document List ──> GET /documents (filters/sort/page)
 |
 +---- Document Detail ──> GET /documents/:id (+ chunks/pages tabs)
 |
 +---- Ingestion Status ──> GET /ingestion/runs (poll 5s while active)
 |       |
 |       +── terminal? ──> invalidate detail/inspectors once
 |       +── failed? ──> lazy GET /ingestion/runs/:id for failure_reason
 |
 v
React Query cache (documentsKeys.* + dashboardKeys.compliance)
```
