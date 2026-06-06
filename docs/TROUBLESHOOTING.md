# Troubleshooting Guide

> Common issues and how to fix them. Organised by symptom.

## "Service unavailable" / 5xx errors

### Symptom

The API returns 5xx. The web UI shows a banner.

### Diagnose

1. Check the health probe:
   ```bash
   curl -i https://<host>/health/live
   curl -i https://<host>/health/ready
   ```
2. Tail the logs:
   ```bash
   docker compose -f docker-compose.production.yml logs --tail 200 backend
   ```
3. Look for `level=error` entries; each has a `request_id` you can
   search for across the entire stack.

### Common causes

* **PostgreSQL is down** — `/health/ready` reports `postgres: down`.
  Restart it: `docker compose -f docker-compose.production.yml restart
  postgres`.
* **Migrations not applied** — the backend logs `relation "..." does
  not exist`. Run `alembic upgrade head` (see
  `docs/ADMIN_GUIDE.md#apply-a-migration`).
* **JWT secret missing or too short** — the backend logs
  `REGINTEL_JWT_SECRET is not set` or `secret must be at least 32
  characters`. Set the env var and restart.
* **LLM provider rate-limited** — the backend logs `rate limit
  exceeded` from the LLM client. Reduce concurrency or upgrade the
  provider tier.

## "Authentication failed" / 401 errors

### Symptom

The UI says "Session expired" or "Authentication failed".

### Diagnose

1. Check the JWT:
   ```bash
   curl -i -H "Authorization: Bearer $JWT" https://<host>/api/v1/security/auth/me
   ```
2. Decode the JWT at <https://jwt.io> and check `exp`.

### Common causes

* **Token expired** — refresh it via `POST /api/v1/security/auth/refresh`.
* **Wrong audience or issuer** — the JWT was issued for a different
  environment. Re-authenticate against the current host.
* **JWT secret rotated** — re-authenticate. See
  `docs/ADMIN_GUIDE.md#rotate-the-jwt-secret`.

## "Permission denied" / 403 errors

### Symptom

The API returns 403. The UI shows "You don't have permission".

### Diagnose

```bash
curl -s -H "Authorization: Bearer $JWT" \
  https://<host>/api/v1/security/auth/me | jq
```

Check that your role includes the required permission.

### Common causes

* **Wrong role** — ask your admin to grant the right role.
* **Missing scope** — the JWT does not include the scope required for
  the endpoint.
* **CORS** — the request was made from an origin not in
  `REGINTEL_CORS_ORIGINS`. Ask your admin to add the origin.

## "Rate limit exceeded" / 429 errors

### Symptom

The API returns 429 with a `Retry-After` header.

### Diagnose

```bash
curl -i -H "Authorization: Bearer $JWT" https://<host>/api/v1/agent/run \
  -X POST -d '{"query":"x"}' -H 'Content-Type: application/json'
```

Check the `X-RateLimit-Remaining` and `Retry-After` headers.

### Common causes

* **Per-IP rate limit** — the nginx limit is 100 rps. Reduce
  concurrency.
* **Per-user quota** — the user is over their daily token budget.
  Wait until tomorrow or ask your admin to increase the quota.

## "Agent didn't answer" / timeout

### Symptom

The agent returns a partial answer with `truncated: true` or times
out.

### Diagnose

Check the agent run logs:

```bash
docker compose -f docker-compose.production.yml logs backend | \
  grep 'logger=app.agent'
```

### Common causes

* **max_steps exhausted** — the planner looped more than 6 times.
  Either refine the query (be more specific) or increase
  `REGINTEL_AGENT_MAX_STEPS`.
* **max_tokens exhausted** — the LLM hit the per-run token budget.
  Increase `REGINTEL_AGENT_MAX_TOKENS` or shorten the conversation
  history.
* **LLM provider timeout** — the upstream LLM took longer than the
  default 30 s. Increase `REGINTEL_LLM_TIMEOUT` or contact the
  provider.

## "Citations are missing"

### Symptom

The agent's answer has no citations, or the citations don't resolve.

### Diagnose

* Open the **Evidence** panel in the UI.
* If it's empty, the retriever found no chunks. Check the filters.
* If it's non-empty but the answer doesn't cite them, the verifier
  rejected the answer and the agent retried but ran out of budget.

### Common causes

* **Filters too narrow** — the retriever returns no candidates.
  Remove the filters or broaden them.
* **Knowledge graph empty** — the documents haven't been ingested
  yet. Wait for ingestion to complete.
* **Verifier disabled** — `REGINTEL_AGENT_VERIFIER_ENABLED=false`
  lets the agent answer without citations. Re-enable it.

## "Document upload failed"

### Symptom

`POST /api/v1/documents` returns 4xx or 5xx.

### Diagnose

```bash
curl -i -X POST https://<host>/api/v1/documents \
  -H "Authorization: Bearer $JWT" \
  -F file=@report.pdf \
  -F metadata='{"source":"FCA"}'
```

### Common causes

* **Unsupported file type** — only PDF, DOCX, HTML, and plain text are
  supported. Convert the file or contact support.
* **File too large** — default limit is 50 MB. Increase
  `REGINTEL_MAX_UPLOAD_SIZE` if you need more.
* **Duplicate SHA-256** — the document is already in the system.
  The response is `409 Conflict` with a `document_id` you can use.
* **Parsing failure** — the parser can't extract text. Check the
  logs for `parser.error`; the most common cause is a scanned PDF
  without OCR.

## "Knowledge graph query is slow"

### Symptom

`POST /api/v1/kg/query` takes more than 1 second.

### Diagnose

```sql
EXPLAIN ANALYZE
SELECT * FROM kg_relations
WHERE source_id = '...' AND kind = 'SUPERSEDES';
```

### Common causes

* **Missing index** — make sure the composite index on
  `(source_id, kind)` exists.
* **Deep traversal** — reduce `depth` or restrict `kinds`.
* **Cold cache** — the first run is always slower. Run it again.

## "PostgreSQL out of connections"

### Symptom

The backend logs `FATAL: too many clients already`.

### Diagnose

```sql
SELECT count(*) FROM pg_stat_activity;
SHOW max_connections;
```

### Common causes

* **Connection pool exhausted** — increase
  `REGINTEL_DB_POOL_SIZE` and `REGINTEL_DB_MAX_OVERFLOW`.
* **Long-running query** — find and kill it:
  ```sql
  SELECT pg_cancel_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'active' AND now() - query_start > interval '5 minutes';
  ```

## "JWT secret rotation broke the API"

### Symptom

After rotating `REGINTEL_JWT_SECRET`, every request returns 401.

### Cause

The new secret is in the env var, but the backend was not restarted.

### Fix

```bash
docker compose -f docker-compose.production.yml up -d --force-recreate backend
```

All existing JWTs are now invalid; users must re-authenticate.

## "Frontend shows a blank page"

### Symptom

`https://<host>/` returns 200 but the page is blank.

### Diagnose

1. Open the browser dev tools → **Console** → look for errors.
2. Open **Network** → reload → look for failed requests.

### Common causes

* **API base URL is wrong** — check the `VITE_API_BASE_URL` build
  arg. The frontend was built with a different host.
* **CORS error** — the backend rejects the origin. Add it to
  `REGINTEL_CORS_ORIGINS`.
* **Mixed content** — the frontend is HTTPS but the API is HTTP.
  Make sure the API is behind HTTPS.

## "Benchmark run failed"

### Symptom

`POST /api/v1/benchmark/run` returns an error.

### Diagnose

```bash
docker compose -f docker-compose.production.yml logs backend | grep -i benchmark
```

### Common causes

* **No targets registered** — the benchmark service is in an
  inconsistent state. Restart the backend.
* **Memory pressure** — the load tester allocates a large buffer
  per concurrent request. Reduce `concurrency`.

## "I lost my admin password"

### Symptom

You can't sign in as admin.

### Fix

The platform uses SSO; there is no password to lose. If SSO is down,
provision a new admin via the identity provider.

If you have a self-hosted deployment with the dev token endpoint
enabled, you can mint an admin token:

```bash
curl -X POST https://<host>/api/v1/security/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"subject": "recovery", "roles": ["admin"]}'
```

Then **disable the dev token endpoint** as soon as you're back in
control.

## "Where do I find the logs?"

| Service | Path |
|---------|------|
| Backend (Docker) | `docker compose logs backend` |
| Backend (Kubernetes) | `kubectl logs deploy/regintel-backend` |
| Frontend (Docker) | `docker compose logs frontend` |
| PostgreSQL | `docker compose logs postgres` |
| Audit log (JSONL) | `/var/log/regintel/audit.jsonl` (configurable) |
| Threat events | `/api/v1/security/threats/recent` |
| Audit records | `/api/v1/security/audit/records` |

## Getting more help

* `#regintel-ops` Slack channel (internal).
* `support@regintel.ai`.
* GitHub issues: <https://github.com/regintel/regintel-ai/issues>.
