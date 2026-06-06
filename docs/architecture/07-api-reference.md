# 07 — API Reference

## Conventions

* **Base URL** — `https://<host>/api/v1/`
* **Auth** — `Authorization: Bearer <jwt>`. JWT is HS256, issued by
  `/api/v1/security/auth/token`. Tokens expire after 1 hour (access)
  and 24 hours (refresh).
* **Content type** — `application/json` for requests; responses are
  JSON. Multipart for document upload.
* **Errors** — RFC 7807 problem+json. Standard error codes:
  * `400` — validation error
  * `401` — missing or invalid token
  * `403` — insufficient role/permission
  * `404` — resource not found
  * `409` — conflict (e.g. duplicate document)
  * `422` — semantic validation error
  * `429` — rate limit exceeded
  * `500` — internal server error (always logged with request_id)
* **Rate limit** — 100 rps per IP for `/api/*`. Specific endpoints may
  apply stricter limits.
* **Request ID** — every request gets a UUID `X-Request-ID` (echoed in
  the response). The same ID appears in logs and audit.

## Core endpoints

### `POST /agent/run`

Run a single agent turn.

```http
POST /api/v1/agent/run
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "query": "What does MiFID II say about best execution?",
  "history_id": "abc123",          // optional: continue a conversation
  "max_steps": 6,                  // optional override
  "expand_graph": true             // optional
}
```

**Response 200**

```json
{
  "answer": "Under Article 27 of MiFID II ...",
  "citations": [
    { "chunk_id": "chk_abc", "document_id": "doc_xyz", "page": 12, "score": 0.93 }
  ],
  "evidence_hash": "sha256:...",
  "request_id": "req_...",
  "duration_ms": 2400,
  "tokens": 3120,
  "cost_usd": 0.014
}
```

### `POST /retrieval/search`

Hybrid retrieval only (no LLM call).

```http
POST /api/v1/retrieval/search
{
  "query": "best execution",
  "top_k": 10,
  "filters": { "jurisdiction": "EU" },
  "expand_graph": true
}
```

### `POST /documents` (multipart)

Upload a document. SHA-256 deduplication; re-uploading the same
content is a no-op.

```http
POST /api/v1/documents
Content-Type: multipart/form-data

file=@report.pdf
metadata={"source": "FCA", "published_at": "2026-01-15"}
```

### `GET /documents/{id}`

Fetch a document, its versions, and chunk count.

### `POST /governance/decisions`

Create a new governance decision.

### `POST /kg/query`

Run a graph query.

```http
POST /api/v1/kg/query
{
  "entity": "MiFID II",
  "depth": 2,
  "kinds": ["SUPERSEDES", "REFERENCES"]
}
```

### `POST /security/auth/token`

Issue a JWT pair. **Dev only** — disable in production by setting
`SECURITY_DEV_TOKEN_ENDPOINT=false`.

```http
POST /api/v1/security/auth/token
{
  "subject": "alice",
  "roles": ["analyst"],
  "scopes": ["read:public"]
}
```

### `POST /security/auth/refresh`

Exchange a refresh token for a new pair.

### `GET /security/auth/me`

Return the resolved principal for the bearer token.

### `GET /security/audit/records`

Filterable, paginated audit log.

```http
GET /api/v1/security/audit/records?status_min=400&limit=50
```

### `POST /security/audit/review`

Mark an audit record as `pending`, `approved`, or `rejected`.

### `GET /security/audit/export?format=jsonl|csv`

Export the filtered audit log.

### `GET /security/threats/recent`

List recent threat events (in-memory ring buffer).

### `POST /security/threats/inspect`

Manually run threat detection against a synthetic request.

### `GET /security/monitoring/dashboard`

Aggregate dashboard: threats, audit, secrets, alerts.

### `POST /benchmark/run`

Run a benchmark suite.

```http
POST /api/v1/benchmark/run
{
  "suite": "quick",
  "iterations": 100,
  "concurrency": 8
}
```

### `GET /benchmark/reports/{kind}`

List available reports (`latency`, `cost`, `agent`, `system`).

## Pagination

All `list` endpoints accept `limit` (1–1000) and `offset` (≥ 0). The
response includes `count`, `limit`, `offset`, and a `next_offset` field
when more results are available.

## Versioning

* The API version is part of the path (`/api/v1/...`).
* Breaking changes bump the major version.
* Deprecations are announced via the `Deprecation` and `Sunset` headers
  at least 6 months in advance.

## Cross-Origin Resource Sharing

* `Access-Control-Allow-Origin` is the request origin if it matches the
  configured allow-list; empty otherwise.
* `Access-Control-Allow-Credentials` is set only when
  `REGINTEL_CORS_ALLOW_CREDENTIALS=true` and the origin is on the
  allow-list.
* `Access-Control-Max-Age` is 600 seconds (10 minutes) by default.

## OpenAPI

* `/openapi.json` returns the OpenAPI 3.1 schema.
* `/docs` (Swagger UI) and `/redoc` (ReDoc) are available in dev. In
  production, gate them behind admin authentication.


## See also

* [Architecture index](./README.md)
* [01 â€” System Architecture](./01-system-architecture.md)
* [05 â€” Data Flow](./05-data-flow.md)
* [06 â€” Components](./06-components.md)
* [07 â€” API Reference](./07-api-reference.md)

