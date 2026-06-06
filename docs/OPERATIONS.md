# Operations Guide

> Day-2 operations for RegIntel AI v1.0.0. Read this after the
> initial deployment in `docs/DEPLOYMENT.md`.

## SLOs

| SLI | SLO | Measurement |
|-----|-----|-------------|
| Availability | 99.9% monthly | `regintel_up{job="backend"} == 1` over 30 days |
| p99 request latency | < 2 s | `histogram_quantile(0.99, ...)` over 5 m |
| Agent p99 latency | < 5 s | `histogram_quantile(0.99, ...)` over 5 m |
| Retrieval p99 latency | < 500 ms | `histogram_quantile(0.99, ...)` over 5 m |
| Error rate | < 0.5% | `rate(5xx) / rate(all)` over 5 m |
| LLM token cost / day | per quota | `sum(rate(llm_tokens_total[1d]))` |

## Monitoring stack

* **Metrics** — Prometheus + Grafana.
* **Logs** — structured JSON to stdout; ship to Loki / CloudWatch /
  Datadog.
* **Traces** — OpenTelemetry → OTLP → Jaeger / Tempo / Honeycomb.
* **Alerts** — Alertmanager / PagerDuty / Opsgenie.

### Dashboards

The Grafana dashboards are in `dashboards/`:

* `regintel-overview.json` — request rate, error rate, latency, top
  routes, top errors.
* `regintel-agent.json` — agent runs, p50/p99 latency, token cost,
  verifier rejections.
* `regintel-retrieval.json` — retrieval p50/p99, recall, KG expansion
  cost.
* `regintel-cost.json` — LLM token usage, cost per tenant, daily
  trend.
* `regintel-security.json` — threat events, audit volume, failed
  auth, alert counts.

Import them via `Grafana → Dashboards → Import → Upload JSON file`.

## On-call

### Severity definitions

| Sev | Definition | Response |
|-----|------------|----------|
| Sev-1 | Service down, all users impacted | Page primary, ack in 5 m |
| Sev-2 | Major feature broken, multiple users | Page primary, ack in 15 m |
| Sev-3 | Minor bug, single user | Ticket, fix in next business day |
| Sev-4 | Cosmetic / question | Backlog |

### Runbooks

* **API 5xx** — `docs/architecture/09-operations-guide.md#runbook-api-returning-5xx`
* **Suspicious activity** — `docs/architecture/09-operations-guide.md#runbook-suspicious-activity`
* **PostgreSQL failover** — `docs/architecture/09-operations-guide.md#runbook-postgresql-failover`
* **Cost spike** — `docs/architecture/09-operations-guide.md#runbook-cost-spike`

## Deployment cadence

* **Patch releases** (`v1.0.1`) — weekly, security + bug fixes only.
* **Minor releases** (`v1.1.0`) — monthly, new features, no breaking
  changes.
* **Major releases** (`v2.0.0`) — quarterly, with a 6-month deprecation
  notice.

## Database maintenance

* **Vacuum** — autovacuum is enabled. Monitor
  `pg_stat_user_tables.n_dead_tup` for tables with high dead-tuple
  ratios.
* **Reindex** — schedule a weekly `REINDEX CONCURRENTLY` on hot
  indexes (chunks, audit, relations).
* **Migration** — see `docs/RELEASE_CHECKLIST.md`. Always test on
  staging first.

## Capacity planning

* Backend scales horizontally; the gunicorn worker count is
  `(2 × CPU) + 1`.
* PostgreSQL: read replicas for retrieval-only workloads.
* Object storage: provider-managed, scales automatically.
* LLM provider: per-minute quota per tenant; set in
  `REGINTEL_LLM_TENANT_QUOTA`.

## Disaster recovery

| Scenario | RTO | RPO |
|----------|-----|-----|
| Single pod failure | 30 s | 0 |
| AZ failure | 5 m | 1 h |
| Region failure | 30 m | 1 h |
| Database corruption | 1 h | 1 h (last base backup) |
| Accidental delete | 5 m | 1 h |

The full DR procedure is in
`docs/architecture/09-operations-guide.md#disaster-recovery`.

## Security operations

* **Patch** — keep the base image and dependencies up to date. The
  Dependabot config at `.github/dependabot.yml` opens weekly PRs.
* **Scan** — Trivy runs on every PR and on every image push. Critical
  findings block the release.
* **Rotate** — rotate the JWT secret every 90 days. Document the
  rotation in the on-call log.
* **Audit** — review the audit log weekly for `status=403` and
  `status=401` spikes.
* **Threats** — review the threat dashboard daily. Investigate any
  `critical` event within 1 hour.

## Cost management

* Set per-tenant quotas in the admin UI.
* Set a global daily budget in `REGINTEL_LLM_DAILY_BUDGET_USD`.
* When the budget is exceeded, the agent falls back to a cached
  response and logs a warning.
* Review the cost dashboard weekly.

## Change management

* All changes go through a PR.
* Migrations are reviewed by a DBA.
* Releases are tagged semver; rollback is `kubectl rollout undo` (or
  `docker compose down && docker compose up -d` with the previous
  tag).
* The release checklist (`docs/RELEASE_CHECKLIST.md`) is mandatory.

## Compliance

* GDPR — user data can be exported via
  `GET /api/v1/admin/users/{id}/export` and deleted via
  `DELETE /api/v1/admin/users/{id}`. Audit log entries are kept for
  the statutory period.
* SOC 2 — see `compliance/soc2/` for the latest report.
* ISO 27001 — see `compliance/iso27001/`.

## Communication

* Status page: status.regintel.ai (updated by the on-call scripts).
* Internal: `#regintel-ops` Slack channel.
* External: `support@regintel.ai`.
