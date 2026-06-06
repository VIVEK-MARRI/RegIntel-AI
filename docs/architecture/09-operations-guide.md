# 09 — Operations Guide

## Health probes

| Probe | Path | Use |
|-------|------|-----|
| Liveness | `/health/live` | Process up? |
| Readiness | `/health/ready` | Dependencies (DB, LLM) reachable? |
| Security self-test | `/api/v1/security/selftest` | Smoke-test security primitives |
| Benchmark health | `/api/v1/benchmark/health` | Benchmark service registered? |

Kubernetes example:

```yaml
livenessProbe:
  httpGet: { path: /health/live, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 10
readinessProbe:
  httpGet: { path: /health/ready, port: 8000 }
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 3
```

## Metrics

Prometheus-format metrics are exposed at `/metrics`.

### Key SLIs

| SLI | Query |
|-----|-------|
| Request success rate | `sum(rate(regintel_http_requests_total{status!~"5.."}[5m])) / sum(rate(regintel_http_requests_total[5m]))` |
| p99 request latency | `histogram_quantile(0.99, sum by (le, route) (rate(regintel_http_request_duration_seconds_bucket[5m])))` |
| Agent run success rate | `sum(rate(regintel_agent_run_total{outcome="ok"}[5m])) / sum(rate(regintel_agent_run_total[5m]))` |
| Retrieval p95 latency | `histogram_quantile(0.95, sum by (le) (rate(regintel_retrieval_duration_seconds_bucket[5m])))` |
| Threat event rate | `sum by (type) (rate(regintel_security_threats_total[5m]))` |
| LLM token cost | `sum(rate(regintel_llm_tokens_total[1h]))` |

### Alerts (Prometheus rule examples)

```yaml
groups:
  - name: regintel
    rules:
      - alert: RegIntelHighErrorRate
        expr: |
          sum(rate(regintel_http_requests_total{status=~"5.."}[5m]))
            / sum(rate(regintel_http_requests_total[5m])) > 0.05
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "RegIntel API error rate > 5%"
      - alert: RegIntelSlowRetrieval
        expr: |
          histogram_quantile(0.95,
            sum by (le) (rate(regintel_retrieval_duration_seconds_bucket[5m]))
          ) > 0.5
        for: 10m
        labels: { severity: warning }
      - alert: RegIntelCriticalThreat
        expr: increase(regintel_security_threats_total{level="critical"}[5m]) > 0
        for: 0m
        labels: { severity: critical }
```

## Logs

Structured JSON to stdout. Required fields:

```json
{
  "ts": "2026-06-06T12:00:00.000Z",
  "level": "info",
  "logger": "app.retrieval",
  "msg": "search completed",
  "request_id": "req_...",
  "route": "/api/v1/retrieval/search",
  "status": 200,
  "duration_ms": 42,
  "principal": "alice",
  "tokens_in": 12,
  "tokens_out": 380
}
```

### Search recipes (Loki / CloudWatch)

* All errors in the last 1 hour:
  `{level="error"} | json | route=~"/api/.*"`
* Slow agent runs (over 4 s):
  `{logger="app.agent"} | json | duration_ms>4000`
* Failed auth attempts:
  `{logger="app.security"} | json | event="auth_failed"`

## Audit log

* In-memory ring buffer (default 10 000 entries) + optional JSONL
  archive at `audit_log.jsonl`.
* Queryable via `/api/v1/security/audit/records`.
* Exportable as JSONL or CSV via `/api/v1/security/audit/export`.

### Retention

| Tier | Default retention | Notes |
|------|-------------------|-------|
| In-memory | 10 000 entries | Ring buffer; not durable |
| JSONL archive | 90 days | Rotated daily |
| Object storage | 1 year | Optional; set `REGINTEL_AUDIT_S3_BUCKET` |

## Incident response

### Runbook: API returning 5xx

1. **Check the dashboard** — `dashboards/regintel-overview.json` for
   the request rate, error rate, p99 latency.
2. **Tail the logs** — `kubectl logs -f deploy/regintel-backend | jq 'select(.level=="error")'`.
3. **Inspect the dependency** — `/health/ready` returns a JSON list
   of dependency probes. If the DB is unhealthy, check
   `pg_stat_activity` for long-running queries.
4. **Check the LLM provider** — `GET /api/v1/llm/health` (if
   configured). If the LLM is degraded, the agent falls back to a
   cached response.
5. **Roll back** — if the regression is correlated with a release,
   roll back to the previous tag:
   `kubectl rollout undo deploy/regintel-backend`.

### Runbook: Suspicious activity

1. **Check the threat dashboard** — `/api/v1/security/threats/recent`.
2. **Inspect the audit log** — filter by `client_ip` or
   `api_key_id`.
3. **Rotate the JWT secret** if the incident indicates a leak:
   `REGINTEL_JWT_SECRET=<new-secret> kubectl rollout restart deploy/regintel-backend`.
4. **Block the IP** at the edge:
   `nginx` reload with the new `denied_cidrs` list, or
   `kubectl apply -f networkpolicy/deny.yaml`.
5. **Notify the security team** via the on-call rotation.

### Runbook: PostgreSQL failover

1. Promote the read replica: `aws rds promote-read-replica --db-instance-identifier regintel-replica-1`.
2. Update the connection string in the secret store.
3. Restart the backend: `kubectl rollout restart deploy/regintel-backend`.
4. Verify readiness: `curl https://<host>/health/ready`.
5. Post-mortem within 24 hours; update this runbook with lessons
   learned.

### Runbook: Cost spike

1. Check the cost dashboard: `dashboards/regintel-cost.json`.
2. Identify the noisy tenant via `api_key_id` or `user_id` in
   `regintel_llm_tokens_total`.
3. Apply a quota: `POST /api/v1/api-keys/{id}/quota` with a lower
   `tokens_per_minute`.
4. If the spike is from anonymous traffic, enable the CAPTCHA on
   `/api/v1/agent/run`.

## Capacity planning

| Resource | SLO | Headroom |
|----------|-----|----------|
| Backend CPU | 70% at peak | 1.5× |
| Backend memory | 80% at peak | 1.3× |
| PostgreSQL CPU | 60% at peak | 1.7× |
| PostgreSQL connections | 80% of `max_connections` | 1.3× |
| LLM tokens / day | per-quota | n/a |
| Object storage | 80% of bucket quota | 1.5× |

### Scaling the backend

* Horizontal: increase the replica count behind the load balancer.
* Vertical: bump the pod's `resources.requests` and `resources.limits`.
* The gunicorn worker count is auto-derived from
  `(2 × CPU) + 1`.

### Scaling the database

* Vertical: bump the instance class.
* Read replicas: route retrieval-only workloads to the replica by
  setting `REGINTEL_DB_READONLY_URL`.
* pgvector: for > 10M chunks, consider an external vector database
  (Qdrant, Milvus) and a thin adapter.

## Backups

| What | Tool | Frequency | Retention |
|------|------|-----------|-----------|
| PostgreSQL | `pg_basebackup` + WAL | Hourly + continuous WAL | 30 days |
| Object storage | Provider-native versioning | Continuous | 30 days |
| Audit log | Daily tar.gz → object storage | Daily | 1 year |
| Secrets | Vault backup | Daily | 30 days |

## Disaster recovery

* **RPO** — 1 hour (PostgreSQL WAL archive + hourly base backup).
* **RTO** — 30 minutes (warm standby, runbook documented).
* **Region failure** — promote the cross-region replica, update DNS,
  restart backend, validate via the smoke test suite.

## Change management

* All changes go through a PR with at least one approving review.
* Database migrations are reviewed by a DBA.
* The release pipeline produces a SBOM and a provenance attestation.
* Releases are tagged semver (`vX.Y.Z`).
* Rollback plan documented in every release PR.

## On-call

* Primary: on-call rotation (PagerDuty).
* Secondary: dev team lead.
* Escalation: VP Engineering.
* Communication: `#incidents` Slack channel.
* Status page: status.regintel.ai (updated by the runbook scripts).


## See also

* [Architecture index](./README.md)
* [01 â€” System Architecture](./01-system-architecture.md)
* [05 â€” Data Flow](./05-data-flow.md)
* [06 â€” Components](./06-components.md)
* [07 â€” API Reference](./07-api-reference.md)

