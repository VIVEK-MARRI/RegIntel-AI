# Dashboard Architecture — STAGE 06

## 1. Product purpose

Operational entry point: system state at a glance, items needing
attention, and paths to continue work. Target user: any authenticated
operator/analyst. Unified across roles (no endpoint returns role-scoped
dashboard data).

## 2. Information hierarchy

1. Header (title, description, manual Refresh).
2. KPI strip (4 authoritative counters).
3. Attention (risk overview + alerts).
4. System (impact distribution + monitoring/services).
5. Pipeline totals (trend counters, text form).
6. Recent work (research + assessments, informational).
7. Continue-work CTAs (Upload, Copilot, Compliance — all real routes).

## 3. Data-source inventory

| Dashboard datum | API | Field | Meaning | Pagination | Freshness |
|---|---|---|---|---|---|
| Documents ingested | `GET /dashboard/compliance` | `documents_ingested` | Registry counter (authoritative, not list length) | n/a (scalar) | 60s stale |
| KG nodes / edges | same | `knowledge_graph_nodes/_edges` | Graph totals | n/a | 60s |
| Research reports | same | `research_reports` | Generated report count | n/a | 60s |
| Pending / critical alerts | `GET /dashboard/alerts` | `by_status.pending`, `by_severity.critical` | Queue depth | n/a | 60s |
| Risk level/score/insights | `GET /dashboard/insights` | `risk_level/score`, `insights[]` | Aggregate posture + attention items | n/a | 60s |
| Alert volume | alerts view | `total`, `by_severity`, `delivery_rate` | Queue composition | n/a | 60s |
| Impact distribution | `GET /dashboard/impact-distribution` | `counts{}`, `total`, `average_score` | Reports by level | n/a | 60s |
| Monitoring | `GET /dashboard/monitoring` | sources/discovered/failures/last_run | Pipeline health | n/a | 60s |
| Components | `GET /dashboard/system` | `components{}`, `uptime_seconds` | Per-service ok/degraded/down | n/a | 60s |
| Pipeline totals | `GET /dashboard/trends` | `items[].points[last].value` | Cumulative counters | n/a | 60s |
| Report rows | `GET /research` | `items[0..5]` + `generated_at` | Latest reports | First page only | 60s |
| Assessment rows | `GET /compliance-risk/assessments` | `items[0..5]` + `generated_at` | Latest assessments | First page only | 60s |
| Global health | HealthProvider (`/health/ready`) | existing | Shell pill (not duplicated) | 30s poll | provider-owned |

“Open reviews”, “active agents”, governance `active`, and list-length
totals were removed: the backend exposes cumulative totals only, and
the UI no longer mislabels them.

## 4. KPI definitions

- **Documents ingested** = `compliance.documents_ingested` (registry
  counter; immune to list `limit` caps).
- **Knowledge graph** = `compliance.knowledge_graph_nodes` (+ edges hint).
- **Research reports** = `compliance.research_reports` (generated count).
- **Pending alerts** = `alerts.by_status.pending ?? 0` (+ `critical`
  hint from `by_severity`). Zero renders `0` + "None critical" —
  a legitimate zero, not an error.

## 5. Query architecture

Nine independent `useQuery` hooks (7 dashboard views + research +
assessments), all parallel, `staleTime: 60_000` (dashboard data moves
slowly; avoids refetch loops on tab switches). Shared responses are
read by one query each — no duplicate requests.

## 6. Query-key usage

`dashboardKeys.*` factories (new in Stage 06) + existing
`researchKeys.reports()` / `complianceKeys.assessments()`. Later
mutations invalidate these: ingestion → `documentsKeys` + dashboard
compliance; research run → `researchKeys` (+ dashboard on summary
change); compliance run → `complianceKeys` (+ dashboard).

## 7. View-model/adapters

DTO names are display-ready; no adapter layer was needed beyond
`toMillis()` timestamp normalization at render. (If DTOs drift, Stage 02
contract tests + drift script catch it.)

## 8–10. Loading / error / empty states

Per-widget `Skeleton` → content; failures render `ErrorState` with
query-scoped retry (widgets fail independently); KPI failures render
the literal `"Unavailable"` (never `0`); empty collections render
`EmptyState` (alerts, impact, trends, reports, assessments; insights).

## 11. Health integration

Dashboard consumes NO health endpoint directly. Global state comes from
`HealthProvider`; the dashboard `system` view shows per-component
ok/degraded/down from the backend aggregator (a different, complementary
signal). No second polling system exists.

## 12. Activity sources

Research reports (`query/summary`, `kind`, `generated_at`) and risk
assessments (`document_id`, `risk_level/score`, `generated_at`) — first
page, capped at 5, timestamps via `toMillis`. Rows are informational
(no detail routes exist); they carry no hover/click affordance.

## 13. Chart decisions

TrendSeries carry single "current"/"total" points — NOT time series —
so line/area charts would be decoration. Decision: NO chart library
(`recharts` stays removed); impact distribution renders as a CSS
segmented bar (`role="img"` + full textual counts); trend deltas render
as direction text. Revisit only when the backend emits real series.

## 14. Navigation destinations

Upload Document → `/documents`; Ask Copilot → `/copilot`;
Open Compliance → `/compliance`. Activity rows navigate nowhere (no
detail routes); the Impact tab is untouched.

## 15. Responsive strategy

KPI `grid-cols-2 sm:4`; attention/system/activity `1col → lg:2col`;
trend tiles `2 → sm:4`; tables scroll via shared `Table`; CTAs wrap.
Verified 390/768/1024/1440 with zero horizontal overflow (screenshots
in `landing/_review/ds-*`, gitignored).

## 16. Accessibility decisions

Single `h1`; labeled landmark sections; status text always accompanies
color (badges, levels, severities); impact bar is `role="img"` with a
complete textual equivalent beside it; buttons named; errors use
`ErrorState` (`role="alert"`); skeletons are `aria-hidden`.

## 17. Invalidation strategy

See §6. Dashboard never mutates. Refresh button invalidates dashboard
+ research + assessment keys (background refetch, no skeleton wipe,
duplicate clicks ignored).

## 18. Known backend limitations

- No open/total split for decisions, reviews, or agents: cumulative
  totals only — hence no "open" KPIs.
- No per-document recency ordering guarantee on list endpoints:
  activity sections avoid "recent" ordering claims.
- Trends are point-in-time counters, not histories.
- Research detail route (`/research/:reportId`) exists in the router
  but the page ignores it (pre-existing; Stage 08).
- Empty stores yield honest zeros (verified live: 23 docs, 24 KG
  nodes, 19 edges, 1 report from dev usage).

## 19. Deferred improvements

Time-series charts when the backend emits series; open/total splits if
the backend adds them; clickable activity rows when detail routes land;
KPI delta trends; customizable layout. None faked in the meantime.

```mermaid
DashboardPage
    |
    +--> getDashboardCompliance / Alerts / Insights / Impact /
    |     Monitoring / System / Trends  (dashboardKeys.*, 60s stale)
    |
    +--> getResearchReports (researchKeys) + getComplianceAssessments
    |
    +--> HealthProvider (global pill; no second poller)
    |
    v
DTOs read directly (toMillis at render)
    |
    v
KPI / Risk+Alerts / System / Trends / Activity / CTA sections
    |
    v
/buttons to /documents /copilot /compliance (rows informational)
```
