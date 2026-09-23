# Compliance Architecture - STAGE 11

## 1. Product purpose
An operational compliance workbench in four tabs — Assessment, Forecast,
Policies, Decisions — where every number is a backend field rendered with its
documented meaning. No percentages, no probabilities, no invented severities.

## 2. Compliance domain model
- **Assessment** (`RiskAssessment`): scored analysis of default signals or a
  referenced change/impact/document. Synchronous, persisted, listed newest-first.
- **Risk** (`risk_score` 0–1 + `RiskLevel`): HIGHER means MORE RISK.
- **Forecast** (`RiskForecast` + `ForecastScenario`): projected scores over a
  horizon from a linear model, plus best/baseline/worst deltas.
- **Policy** (`GovernancePolicy` + `ApprovalPolicy`): versioned, scoped rule
  sets with an `enabled` boolean; role bindings for approvals.
- **Decision** (`GovernanceDecision`): captured AI verdict with an optional
  `policy_result`; re-checkable against current policies.
- Review/alerts/recommendations/changes are SEPARATE backend modules with their
  own workflows and are intentionally not on this page (§23).

```mermaid
flowchart TB
    User --> Page[CompliancePage\nTabs: assessment|forecast|policies|decisions]
    Page --> A[Assessment\nPOST /compliance-risk/assess]
    A --> BE[ComplianceRiskService\nRiskScorer + RiskAnalyzer]
    BE --> R[Risk\nscore 0-1 + level]
    BE --> G[Gaps\nComplianceGap]
    BE --> RA[Recommendations\nRecommendedAction]
    BE --> E[Evidence\nareas + explanation]
    Page --> F[Forecast\nPOST /forecasting/forecast]
    Page --> P[Policies\nGET/PATCH /governance/policies]
    Page --> D[Decisions\nGET /governance/decisions\nPOST .../check]
    Page --> RQ[React Query]
    RQ --> K1[complianceKeys\nstats|trend|assessmentsFiltered]
    RQ --> K2[riskKeys\nstats|forecasts|scenarios]
    RQ --> K3[governanceKeys\npolicies|approvalPolicies|decisions|stats]
```

## 3. Endpoint inventory
Verified in `app/api/v1/*.py` (+ Stage-02 contract tests for assess/forecast/
policies/decisions/stats shapes).

| Method | Path | Use | Notes |
|---|---|---|---|
| GET | `/compliance-risk/stats` | Assessment metrics (NEW) | Real counts incl. critical/high, avg score |
| GET | `/compliance-risk/trend` | Trajectory chart (NEW) | `?document_id=`; ascending points, direction ±0.05 rule |
| POST | `/compliance-risk/assess` | Run (201) | Sync; ONLY document_id/diff_id/impact_report_id/source/context |
| GET | `/compliance-risk/assessments` | History | risk_level/category/document_id/after/before/page/page_size; desc |
| GET | `/forecasting/stats` | Forecast metrics (NEW) | Totals, avg horizon, drift count/rate |
| POST | `/forecasting/forecast` | Run (201) | ONLY document_id/horizon_days/confidence/history |
| GET | `/forecasting/forecasts` | Bare-array history | Full objects — no per-row fetch |
| GET | `/forecasting/scenarios` | Bare-array scenarios | Derived from latest forecast score |
| GET | `/governance/stats` | Governance metrics | Compliance/violation counters, compliance_rate |
| GET | `/governance/policies` | Bare-array policies | scope/enabled_only filters |
| PATCH | `/governance/policies/{id}` | Enable/disable (NEW) | Query-param patch; 404 when unknown |
| GET | `/governance/approval-policies` | Role bindings (NEW) | Bare array, read-only in UI |
| GET | `/governance/decisions` | Paged registry | Type/compliance/model/subject/actor/page filters |
| POST | `/governance/decisions/{id}/check` | Re-check (NEW) | Evaluates; does not rewrite the decision |

## 4. Assessment request model
`RiskAssessmentRequest`: all-optional `document_id/diff_id/impact_report_id/
source/context` (`extra="forbid"` — `scope/policies` 422, contract-tested). The
form offers a stored-document dropdown (real `document_id`), a source select,
and optional change/impact ID fields. With no references the backend scores
default medium signals — the form labels this a baseline, not a scoped finding.
`context` is accepted but NOT exposed (nothing in the UI can fill it honestly).

## 5. Assessment response model
Full `RiskAssessment`: ids, source, level+score, categories, affected areas,
actions, gaps, `explanation` (OBJECT — or legacy string, both handled),
`regulatory_exposure`, `historical_risk_score` + `trend`, `generated_at`,
`duration_ms`. History rows already carry full objects, so detail renders from
the row/response with NO extra fetch.

## 6. Risk model
Score 0–1 plus `RiskLevel` (low|medium|high|critical), categories (8-enum),
affected areas with 0–1 exposure, gaps with severity, actions with priority,
and a `RiskExplanation` (summary + top factors + scoring method).

## 7. Risk score semantics
Resolved from `RiskScorer`: severity/category/impact weights plus breadth and
gap penalties; CRITICAL sources weight 1.0. HIGHER = MORE RISK, stated in the UI
next to every score. Bands from `_to_level` quoted verbatim in a caption:
critical ≥ 0.85, high ≥ 0.65, medium ≥ 0.4, else low.

## 8. Gap/obligation model
`ComplianceGap`: area, severity (RiskLevel), description, regulatory_basis,
remediation_action_id (rendered as a text link-reference to the action id, not
a route). There is NO obligations concept in the backend — no obligations
section exists.

## 9. Recommendation model
`RecommendedAction`: type (10-enum), title, description, priority (RiskLevel),
rationale, estimated_effort_hours. Rendered as-is under the neutral heading
"Recommended actions" (never "Recommended Controls"). `confidence` (backend
constant) is intentionally not displayed (§10).

## 10. Forecast model
`RiskForecast`: horizon, predicted score+level (same 0–1, higher=worse),
`method` (e.g. linear_regression+exponential_smoothing), `points[]` +
`series` (genuine series → SVG line + range band), `drift_detected` flag.
`confidence` echoes the request (default 0.5) and is NOT displayed as a model
signal. `ForecastScenario`: name, `adjustments` (`{delta: ±}`), score, level —
rendered in backend order. The forecasting `/trend/{doc}` endpoint returns a
SINGLE object and gets no chart; the compliance-risk trend (a real series) gets
the trajectory chart.

## 11. Forecast request
`ForecastRequest`: optional `document_id`, `horizon_days` 1–365 (default 30),
`confidence`, `history[]`. The form exposes document + horizon only: confidence
would be an echo knob, and no UI can build a history series honestly.

## 12. Policy model
`GovernancePolicy`: name, description, `version` STRING, `scope` (+value),
`rules[]` (kind/action/severity/enabled + description), `enabled` BOOL,
epoch timestamps, tags. State renders as "Enabled"/"Disabled" — the `enabled`
field verbatim, never "active/draft/archived". Rules expand inline. Policy
create/delete need a rule builder and are deferred; the enabled toggle (PATCH)
is the only mutation, invalidating policies + stats.

## 13. Decision model
`GovernanceDecision`: type (8-enum), `subject_type:subject_id`, `decision`
free-form text, model/version, `risk_level`, categories, actor, epoch
timestamp, `approved_by[]`, optional `policy_result` (compliant bool +
violations with rule/severity/action/message + required actions + evaluated
counts). `confidence` is registrant-reported and shown ONLY with the
"as reported by the registrant" attribution. `inputs/outputs` are free-form
dicts and are not rendered. Decisions are registered by AI systems — no manual
create UI.

## 14. Alert/change/review models
Not on this page. Alerts (`/alerts`), review workflows (`/review` with
approve/reject/escalate), recommendations (`/recommendations`), and change
events (`/changes`, whose model carries NO `impact_score`) are separate modules.
No open-review counts or impact numbers are shown anywhere here.

## 15. Tab architecture
Stage-05 `Tabs` with local state (simplest convention; no routing complexity):
Assessment | Forecast | Policies | Decisions. The old Overview/Impact tabs are
gone — Overview's run+history live in Assessment, and Impact was placeholder
copy with no backend. Tab panels mount on activation, so only the visible tab's
queries fire (deliberate Option-A loading strategy). Keyboard: roving tabindex
with arrows/Home/End from the shared component.

## 16. Query/cache architecture
- `complianceKeys`: `stats()`, `trend(documentId?)`, `assessments()` (paramless
  — Dashboard consumes it with a bare queryFn, zero-touch), NEW
  `assessmentsFiltered(params)`, `assessment(id)` (reserved).
- `riskKeys`: `stats()` (NEW), `forecasts()`, `scenarios()`.
- `governanceKeys`: `policies()`, `approvalPolicies()` (NEW), `decisions(params)`
  (extended — no external bare-fn consumers), `stats()`.
- Documents dropdown reuses canonical `documentsKeys.list({})`.
Local state holds only form values, filters, page, selection, expansions, and
inline check results.

## 17. Mutation/invalidation matrix
- Assess run → invalidate `["compliance","assessments"]` prefix (covers base +
  filtered; refreshes Dashboard's rows too — the allowed narrow cross-page
  effect) + `complianceKeys.stats()`. No other domains.
- Forecast run → `riskKeys.forecasts()` + `scenarios()` (derived from latest
  score — real relationship) + `riskKeys.stats()`.
- Policy toggle → `governanceKeys.policies()` + `governanceKeys.stats()`.
- Decision re-check → NO invalidation (evaluation doesn't rewrite the stored
  decision; the result renders inline from mutation data).

## 18. Loading/error/empty behavior
Per-tab, per-region independence: Skeleton / ErrorState+Retry (ApiClientError
message; 422s surface backend detail safely, never raw objects) / EmptyState
with distinct copy (no assessments/policies/decisions/forecasts/scenarios/
gaps/actions/areas). Expensive runs never auto-retry. `aria-live` on lists,
`role=status` on pending runs, `role=alert` on errors.

## 19. Responsive strategy
Single-column workbench; forms collapse to stacked fields; tables scroll
horizontally in `overflow-x-auto`; scores stay paired with their level text.
Verified 390/768/1024/1440, zero overflow (`landing/_review/ds11-*`,
gitignored local artifacts).

## 20. Accessibility
One h1; tablist keyboard pattern; labelled inputs (hint/error wired via
`Field`); risk/compliance states as text + tone (never color-only); policies
table has caption + scoped column headers; score meaning available as text
(bands caption, direction sentences); chart SVGs are `role=img` with text
summaries and adjacent textual equivalents.

## 21. Security
Stage-02 client throughout; backend remains the authorization boundary (no
route-level role guards exist on governance mutations, so the UI shows actions
to all authenticated users rather than theater-hiding them); ids
path-encoded; no unsafe HTML; model text rendered as text; no tokens logged.

## 22. Performance
Active-tab-only queries; paged histories (50/page) with short-page
heuristics; bare-array endpoints consumed as-is; no per-row detail fetches;
SVG charts are a few dozen nodes; no memoization theater.

## 23. Known backend limitations
- Baseline assessments score default signals; `context` is accepted but unread
  by the scorer.
- Confidence values are constants/echoes (0.85 explanation, 0.5 action
  default, request-echo forecast) — displayed nowhere.
- Compliance trend needs ≥2 stored assessments for a chart.
- Scenarios derive from the latest forecast; empty without one.
- Governance store durability is deployment-dependent (as with other modules).
- No policy create/update-rules/delete, no decision registration, no review
  actions in this UI (see §24).

## 24. Deferred features
Policy rule-builder CRUD, policy delete (destructive — needs confirm UX),
manual decision registration, review/alert/recommendation surfaces, date-range
filters (`after/before` exist server-side), document-picker-driven forecast
history, print/export stylesheets.
