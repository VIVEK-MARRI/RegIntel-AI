# Analytics Architecture - STAGE 13

## 1. Product purpose
Agent-operations analytics: how the backend's AI agents are performing right
now — invocation volumes, success shares with counts, latency distributions,
health states, ranked leaderboard, cost estimates, and invocation breakdowns.
Current-state only; the page states plainly that no historical series exists.

## 2. Backend analytics endpoints discovered
Two analytics backends exist; only one backs this page.

**Used — agent analytics** (`app/api/v1/agent_analytics.py`,
`/agents/analytics/*`; `intelligence_agents.py`, `/agents/metrics`): typed
response models, MSW contract-tested, in-memory counters.

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/agents/analytics/overview` | `AgentAnalyticsOverview` | Totals, 0–1 success share, mean ms, health summary, leaderboard embed, nullable cost, epoch `generated_at` |
| GET | `/agents/analytics/performance` | `AgentPerformance[]` | Bare array, per-agent counts/shares/latency/health |
| GET | `/agents/analytics/performance/{name}/latency` | `LatencyDistribution` | Zero-filled (count 0) when no samples — never 404 |
| GET | `/agents/analytics/leaderboard` | `ForecastScenario[]`-shaped ranks | `?top_n=` (only server filter); composite score |
| GET | `/agents/analytics/health` | `HealthSummary` | Counts + overall + notes |
| GET | `/agents/analytics/cost` | `CostEstimate` | Single object; estimated units |
| GET | `/agents/metrics` | `IntelligenceAgentMetrics` | Totals + `by_mode`/`by_scenario_kind` count dicts |

**Evaluated, excluded — retrieval platform** (`app/api/v1/analytics.py`,
`/api/v1/analytics/*`): RAG-evaluation metrics behind an async DB session,
with untyped `Dict[str, Any]` reads on the key endpoints and engine-owned
write paths. Not stable enough for UI use; documented here, not rendered.
Alerts/changes/recommendations/review modules belong to other surfaces
(Audit, Dashboard) and are not re-shown.

## 3. Metric inventory
- Agents: `overview.total_agents` (count of tracked names).
- Invocations: `overview.total_invocations` (succeeded + failed).
- Success share: `overview.success_rate` 0–1 rendered WITH reconstructed
  counts ("0.90 (9 of 10)") — a deterministic, documented transformation.
- Avg latency: `overview.average_duration_ms`, milliseconds.
- Est. cost: `cost.cost_units` + `currency` + backend `notes` ("Estimated at
  $0.001/invocation"; tokens always 0 in this build — shown as returned).
- Collaborations / mean confidence / counters-since: intelligence aggregates
  with exact labels.
- Health: backend-classified counts + overall (0 invocations → unknown;
  0 failures → healthy; share < 0.5 → unhealthy; else degraded).
- Leaderboard score: `0.6·success + 0.3·confidence + 0.1·speed`, speed 1.0
  below 100ms avg → 0 at/above 5000ms (quoted in-UI from service code).

## 4. Exact semantic meaning of each metric
Documented in §3 and in-UI captions. Shares are proportions of recorded
events, never probabilities or quality grades. Latency is recorded duration
in ms (mean, p50/p90/p95/p99, min/max). Cost units are estimates, not metered
billing. Health is a deterministic function of failures, stated in-UI.

## 5. Current-state vs historical data
Everything is current-state (in-memory counters, reset on backend restart).
NO endpoint returns timestamped history → Section C is an explicit
insufficient-history panel, and zero trend charts, deltas, or forecasts exist.

## 6. Query architecture
Canonical `analyticsKeys`: `overview()`, `performance()`, `intelligence()`,
`health()`, `cost()`, `leaderboard(topN)` (only param-bearing key besides
`latency(name)`), `latency(name)`. Dead `changes()` key removed (no
consumers). Independent queries fire in parallel; per-agent latency loads on
selection only. No polling — manual "Refresh analytics" invalidates the
`["analytics"]` prefix (user-initiated, analytics-scoped only).

## 7. Filters
Exactly one server filter exists and is exposed: leaderboard `top_n`
(number input 1–50, in the query key). No date/regulator/severity filters
exist backend-side, so none are offered. Latency agent selection is
client-side routing to a per-agent endpoint (key includes the name).

## 8. Charting decisions
No charting dependency (none installed; none added). Distributions render as
CSS bars with full textual equivalents (counts listed, `role=img` summaries);
latency percentiles render as a CSS ladder PLUS an accessible data table.
Rationale: 2–3 simple distributions, no interaction needs, minimal bundle
(~14KB page chunk), screen-reader parity by construction. Recharts would add
weight without adding truth.

## 9. Loading/error/empty/insufficient-history behavior
Per-section Skeletons (chart dimensions reserved via fixed bar heights);
ErrorState+Retry per failed region with zero cross-contamination (verified by
test: health failure leaves the rest usable); EmptyStates for no agents /
no samples / no ranks / no breakdowns ("No agent activity", never zeros);
zero-invocation agents show "no invocations", never 0.00; the trends card is
a permanent insufficient-history notice.

## 10. Accessibility approach
One h1; section structure via card headings; bars carry `role=img` summaries
plus adjacent count lists; latency has a real `<table>` with caption + scoped
headers; tables throughout captioned/scoped; controls labelled; no color-only
meaning (every color has adjacent text); keyboard-native buttons/inputs.

## 11. Performance decisions
Bounded bare-array reads; no full-history fetch exists to abuse; latency
detail on selection; no polling timers; no memoization theater; manual
refresh instead of 30s polling (previous behavior removed as unjustified).

## 12. Security/data handling
Stage-02 client only; no raw fetch; backend is the authorization boundary;
last-error strings render as truncated text with full value in `title`
(no HTML); no tokens/secrets; normal path encoding for agent names.

## 13. Backend limitations
- Counters are in-memory (restart resets; `last_reset_at` shown).
- No timestamped history → no trends, deltas, or forecasting.
- Only one server filter (`top_n`); no date/regulator scoping.
- Leaderboard confidence/speed components are backend-weighted constants.
- Cost tokens always 0; rate hardcoded ($0.001/invocation).
- Retrieval platform (`/api/v1/analytics/*`) intentionally unused (§2).
- `recent_executions`/`forecast_accuracy`/`collaborations` arrays in the
  overview payload have no documented UI semantics and are not rendered.

## 14. Deferred analytics features
Retrieval-platform surface (needs typed reads + seeded DB), historical
series (needs backend retention), export (no endpoint), per-agent cost
breakdown (endpoint is platform-total), collaboration graph
(`collaborations` unused), reset action (destructive test helper — no UI).
