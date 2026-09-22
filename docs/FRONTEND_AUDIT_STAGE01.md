# RegIntel Frontend Product Audit — STAGE 01

**Scope:** `frontend/` (authenticated SPA) + its backend contracts (`app/api/v1/*`, `app/schemas/*`, `app/security/*`). **Audit only — zero code changed.**
**Frozen:** `landing/` untouched. **Source of truth:** current code; READMEs/comments distrusted everywhere.
**Method:** full read of all 64 files under `frontend/src`, all services, all pages, all providers/components/tests/configs; every backend endpoint the frontend calls cross-checked against route + schema code. Spot-verified load-bearing claims (Signup hooks order, copilot citation shape).

---

## 1. Repository structure

`frontend/` root: `src/`, `public/` (single `favicon.svg`), `scripts/assemble-static.mjs`, `index.html`, `package.json` (+lock), `vite.config.ts`, `vitest.config.ts`, `tailwind.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `postcss.config.js`, `.eslintrc.cjs`, `Dockerfile.production`, `README.md`. `dist/` is assembled output (landing at root + SPA at `dist/app/`). `node_modules/` present.

| Directory | Files | Responsibility |
|---|---|---|
| `src/` root | `App.tsx`, `main.tsx`, `index.css`, `vite-env.d.ts` (4) | Route table + guard wiring; provider/query/router bootstrap (+ unconditional devtools); Tailwind + `.card/.btn/.badge/.input` component classes; `VITE_*` typings |
| `src/pages/` | 14 | One route view each: Login, Signup, Dashboard, Copilot, Research, Documents, KnowledgeGraph, Compliance, Audit, Analytics, Settings, Agents, Admin, NotFound |
| `src/components/` | 15 | `ui/` ×12 (Button, Card, Badge, Metric, Field, Table, Alert, EmptyState, ErrorState, Skeleton, ProgressBar, ToastViewport) + `layout/AppShell.tsx` (Sidebar/Topbar/UserMenu) + `auth/` (ProtectedRoute, RequireRole) |
| `src/providers/` | 4 | Auth (session/roles/timer-refresh), Health (`/health/ready` 30s poll), Theme (dark class), Toast (ephemerals) |
| `src/services/api/` | 14 (13 domains + `index.ts` barrel) | Typed thin wrappers over `lib/api` request client; barrel **omits `authApi`** (`index.ts:1-12`) |
| `src/lib/` | 3 | `api.ts` (fetch client, base-URL + Bearer, `ApiClientError`, **no 401 handling**), `auth-token.ts` (in-memory `_token`), `format.ts` (formatters) |
| `src/types/` | 1 (`index.ts`, 651 lines) | Loose shared DTOs for all domains — **systematically drifted from backend** (see §7) |
| `src/test/` | 9 (8 suites + `setup.ts`) | `api`, `pages`, `integration` (misnamed), `ui`, `accessibility`, `format`, `ThemeProvider`, `ToastProvider`; jsdom shims; **no MSW** |

Page→service wiring (grep-verified): Dashboard → analytics(documents/research/governance); Copilot → copilot/conversations; Research → research; Documents → documents/ingestion; KG → knowledge-graph; Compliance → compliance-risk/forecasting/governance; Audit → audit; Analytics → analytics; Agents → agents/analytics-health; Admin → admin; Settings → health context only; Login/Signup → auth.

---

## 2. Complete page inventory

| # | Page (file) | Route(s) | Purpose (one line) |
|---|---|---|---|
| 1 | LoginPage | `/app/login` | Credential login → token session |
| 2 | SignupPage | `/app/signup` | Register (raw fetch) → auto-login |
| 3 | DashboardPage | `/app/` | KPI glance + jump-off cards |
| 4 | CopilotPage | `/app/copilot`, `/app/copilot/:conversationId` | Blocking Q&A chat with citations/signals |
| 5 | ResearchPage | `/app/research`, `/app/research/:reportId` (param **never read**) | One-shot research run + report render |
| 6 | DocumentsPage | `/app/documents` | Upload → ingest → browse/search/detail |
| 7 | KnowledgeGraphPage | `/app/knowledge-graph` | Entity list + BFS impact (no graph viz) |
| 8 | CompliancePage | `/app/compliance` (4 local tabs, no sub-routes) | Assessments / forecasts / policies-decisions / static Impact |
| 9 | AuditPage | `/app/audit` (3 local tabs) | Records / integrity / reports / evidence (read-only) |
| 10 | AnalyticsPage | `/app/analytics` | Agent metrics tables (no charts) |
| 11 | SettingsPage | `/app/settings` | Backend truth display + 3 fake editables + working theme |
| 12 | AgentsPage | `/app/agents` (4 local tabs) | Execute / health / workflows / message bus (polling) |
| 13 | AdminPage | `/app/admin` | Read-only users/roles/stats (zero mutations) |
| 14 | NotFoundPage | `*` (**inside** authed shell, unguarded) | Dead-end card linking `/` |

---

## 3. Route map

Entrypoint `main.tsx:29-51`: `BrowserRouter basename={VITE_BASENAME ?? "/app"}` → QueryClient (`retry:1, refetchOnWindowFocus:false, staleTime:30s`) → Theme → Toast → Health → Router → Auth; `ReactQueryDevtools` mounted **unconditionally (incl. prod)**. All 13 pages `React.lazy` + double `Suspense` spinner. `Protect(path, children)` (`App.tsx:38-48`) always applies `ProtectedRoute`, additionally `RequireRole` for `/agents` (`admin,operator,analyst`) and `/admin` (`admin`).

| Path | Component | Access | Layout | API deps |
|---|---|---|---|---|
| `/login` | LoginPage | public (authed bounced to `from`) | none | `POST /security/auth/login` |
| `/signup` | SignupPage | public (authed bounced to `/`) | none | raw `POST /api/v1/security/auth/signup` + login |
| `/` | DashboardPage | auth | ProtectedLayout | analytics-overview, changes, documents, research, gov-stats (5 parallel) |
| `/copilot`, `/copilot/:conversationId` | CopilotPage | auth | ProtectedLayout | sessions, health (discarded), messages (gated), `POST /copilot/query` |
| `/research`, `/research/:reportId` (dead param) | ResearchPage | auth | ProtectedLayout | reports list, `POST /research/run` |
| `/documents` | DocumentsPage | auth | ProtectedLayout | documents, ingestion runs, doc detail (gated), upload |
| `/knowledge-graph` | KnowledgeGraphPage | auth | ProtectedLayout | stats, nodes, impact (gated) |
| `/compliance` | CompliancePage | auth | ProtectedLayout | assessments, assess, forecasts, scenarios, forecast, policies, decisions, stats |
| `/audit` | AuditPage | auth | ProtectedLayout | records, integrity, reports, evidence |
| `/analytics` | AnalyticsPage | auth | ProtectedLayout | overview, performance, intelligence metrics + health ctx |
| `/settings` | SettingsPage | auth | ProtectedLayout | health ctx only |
| `/agents` | AgentsPage | auth + role(3) | ProtectedLayout | agents CRUD-lite, execute, workflows+run, collabs, messages, analytics-health |
| `/admin` | AdminPage | auth + role(admin) | ProtectedLayout | overview, stats, users, roles |
| `*` | NotFoundPage | **effectively public, shell rendered** | ProtectedLayout | none |

**Inconsistencies:** `/research/:reportId` never read (deep links silently list); sidebar hides `/agents` from operator/analyst whom the guard admits (`AppShell.tsx:26` vs `App.tsx:40`); `*` renders full shell for logged-out users (`App.tsx:83`); login drops query/hash, signup ignores `from`; `SPA_BASE` vs `VITE_BASENAME` can diverge (asset vs route base).

---

## 4. Application shell map

`ProtectedLayout` (`App.tsx:23-36`) = fixed `w-64` Sidebar + column(Topbar + scroll `main`) + `ToastViewport`; no `Outlet` composition (inner `<Routes>` repeats absolute paths). Sidebar NAV (9 ungated, matches routes) + admin-gated Agents/Admin links. **Dead/no-op:** hamburger → `()=>{}` with `collapsed={false}` hard-coded (`App.tsx:26,28`); Profile/API Keys/Activity Log menu items only close the menu (`AppShell.tsx:219-229`); **SystemStatusPill hardcoded "All systems operational"** ignoring `HealthProvider` (`AppShell.tsx:168-179`); Sign-out hidden when auth disabled. **No notification center** (the `aria-label="Notifications"` region is the toast stack — real, 4.5s auto-dismiss, Esc). Status pill/username hide below `sm`; Copilot session list `hidden lg:flex` with no mobile alternative → sidebar eats 256px on phones with no drawer escape.

---

## 5. Authentication architecture

```
LOGIN (LoginPage 21-35 → AuthProvider.login 171-197 → authApi.login → POST /security/auth/login)
  → ACCESS (memory _token, lib/auth-token.ts) → Bearer on every lib/api call (66-72)
  → REFRESH (localStorage regintel_refresh_token) → setTimeout((expires_in-30)s) → POST /security/auth/refresh (rotates both)
  → SESSION (localStorage regintel_user + state; restore on reload via refresh attempt 128-169)
  → PROTECTED ROUTE (ProtectedRoute → /login?from=pathname; RequireRole checks user.rbac_roles)
LOGOUT = local wipe only (no server call). SIGNUP = raw fetch + auto-login.
```

- **Storage:** access = memory only (lost on reload); refresh + user/roles = plain readable `localStorage` (XSS-stealable; no HttpOnly cookies anywhere). Demo mode (`VITE_AUTH_ENABLED=false`) synthesizes all-roles user + literal `Bearer demo`, `hasRole→true`, `logout` no-op — a single env misset opens everything.
- **Refresh:** timer-only; **no 401 interceptor/retry** (`lib/api.ts` throws); dead `scheduleRefresh` beside live `scheduleRefreshRef`; floor `max(10000,…)` hammers on short TTL; no dedupe (StrictMode double-POST races rotation); refresh failure = silent `clearTokens` → redirect.
- **Roles:** from login/refresh payload only (`rbac_roles`; `roles` ignored by `hasRole` — latent breakage if backend populates `roles`); `getMe()` dead; tampered `localStorage` grants UI roles until next refresh.
- **Issues:** localStorage refresh theft (High); no logout revocation (Medium); stale-role trust (Med-High); demo kill-switch (High, deployment-gated); Signup Rules-of-Hooks violation — `useState` after early return (`SignupPage.tsx:8-15`, verified; **High/correctness**); raw Signup fetch (`[object Object]` errors); minimal validation (no trim, optional full_name, min-6 only); silent session expiry; tokenless bootstrap race.

---

## 6. API architecture

Core `lib/api.ts`: `BACKEND_BASE=VITE_API_BASE_URL` + `/api/v1` (relative fallback → Vite proxy `/api,/health→localhost:8000`); Bearer iff memory token; `ApiClientError(status,message,detail)` from `.detail`; **no timeout/cancel/retry/unwrap**; `signal` plumbed but zero call-sites pass it; `stream` branch exists, zero call-sites. Bypass clients: `healthApi` (own fetch, root `/health/ready`→401→`/live`, `Error` not `ApiClientError`), `SignupPage` (raw fetch).

**Service inventory** (14 modules; per-function METHOD/PATH/request/response/used-by verified by grep — full table in audit working notes; key facts): ~50 exported functions; **19 dead** (zero prod call-sites): `getAgent/getAgentHealth/getExecution`, `getLeaderboard/getCost/getLatency/getAlerts/getRecommendations/getReviewTasks`, `getAuditRecord`, `getMe`, `getComplianceAssessment`, `getIngestionJob/getDocumentChunks/getDocumentPages`, `getPolicy`, `getGraphRelationships`, `getResearchReport`, `getRiskTrend`; plus `getCopilotHealth` called-but-discarded. Pagination incoherent (two `PaginatedResponse` defs; no service sends page params; bare-array vs `{items}` mixed); unencoded path interpolation everywhere except 2 fns; `POST runWorkflow`/`impact-traversal` send no body; polling 30/15/5s with no backoff vs no polling for ingestion/compliance/audit/KG.

---

## 7. Backend/frontend contract audit ← **the systemic finding**

Prefix/auth ground truth: frontend builds `BACKEND_BASE + /api/v1 + path` — matches (routers mounted `/api/v1`); health correctly special-cased to root `/health/*`. **No data route declares role deps** (`require_role` unused); prod enforcement is middleware Bearer-only; **no route requires `admin`**; `POST /security/auth/logout` **does not exist**. Errors are `{"detail"}` (frontend extracts correctly).

**Nearly every page renders `undefined` somewhere — the frontend DTOs describe a different (older/newer) backend.** Runtime-breaking mismatches (all verified route-vs-schema-vs-type):

| # | Endpoint | Frontend believes | Backend actually is | Effect |
|---|---|---|---|---|
| 1 | `POST /security/auth/refresh` | `LoginResponse` incl. `user` | `TokenResponse`, **no `user`** | `resp.user` → undefined |
| 2 | `GET /health/ready` | `components[]` array | `checks:{}` **map**; `live`=`{status:"alive"}` | `.map` crash; status vocab differs |
| 3 | Admin overview/stats/users/roles | nested users/policies/audit; `name/roles/pending`; `member_count` | flat totals; `username/role_ids/invited`; `user_count` | whole Admin page undefined |
| 4 | Agents detail/health/execute | `config/statistics`; `{health,notes}`; `{execution_id,confidence,started_at!}` | metadata only; `{healthy:bool,…}`; `{result_id,output:Dict,7-enum status}` | detail/health/execute UI broken |
| 5 | Workflows | flat `steps`, `{execution_id}` | nested **`graph.steps`**, `{run_id}`; `POST` SPA shape → **422** (`extra=forbid`, missing `graph`) | create/run broken |
| 6 | `POST /compliance-risk/assess`, `POST /forecasting/forecast` | `{scope,policies}` / `{horizon,baseline,drivers}` | `extra=forbid` forbids those keys | **guaranteed 422** — buttons always fail |
| 7 | Alerts/changes/recommendations/review | `description/detected_at/open…`; `ChangeEvent{impact_score}`; `rationale:string/actions[]` | `message/created_at/pending…`; `DocumentDiff` (no impact_score, ISO time); `reasoning[]/action_plan` | all four shapes break |
| 8 | Audit records/integrity/reports/evidence | `subject/outcome/evidence_ids`; `{broken_chains,checked_at}`; ISO periods + `{heading,body}` | `subject_type+subject_id/severity/…`; `{intact,message,…}` (**compromised chain still renders "Healthy"**); epoch periods + `ReportSection` | 3/6 columns blank; tamper-evidence false |
| 9 | Compliance assessments | `{scope,obligations,gaps…}` | `RiskAssessment` (no scope/obligations; different gaps) | scores `NaN`, detail blank |
| 10 | Copilot `citations/sources/contributions/memory` | `CopilotCitation[]`; `{source_id,relevance}`; `agent_contributions[]`; `{…,entities}` | **`AnnotatedAnswer` object** (`.slice` throws); `SourceAttribution{attribution_id,similarity,…}`; field absent; `MemoryContext{short_term,long_term,retrieval,…}` | citation UI dead/crash-prone; memory half-dead |
| 11 | Conversations | epoch `created_at/updated_at`, `message_count/preview` | **ISO datetimes**, neither field | "Invalid Date" everywhere |
| 12 | Documents list/detail | `chunk_count` on list, `created_at` | detail-only `chunk_count`; `uploaded_at` | dead columns/timestamps |
| 13 | Ingestion runs | `{job_id,queued/running/succeeded,epoch times}` | `{run_id,13-enum (no queued/running/succeeded),ISO times}` | "Active Jobs" permanently 0; success renders amber |
| 14 | Governance policies/decisions/stats | `status enum/version:number/created_by`; `{subject,outcome,policy_ids[],rationale}`; `{active,deprecated}` | `enabled:bool/version:string`; `{subject_type+subject_id,decision,policy_result…}`; neither stat exists | badges/tables wrong; stats `—` |
| 15 | KG nodes/relationships | `{label,type}` / `{rel_id,source,target,type}` | `{name,entity_type,…}` / `{relationship_id,source_id,target_id,relationship_type,…}` | entities render blank; edges unusable |
| 16 | Research reports | `{plan[],findings[],confidence,created_at,sources}` | `{steps[],key_findings:string[],generated_at,…}`, **no confidence**; `completed`≠`done` | 0 steps/findings, blank confidence |
| 17 | Forecasts/trend | `{projected_score,baseline_score,drivers[],created_at}` / `RiskProjection[]` | `{predicted_risk_score,…}`; trend returns a **single object** (`.map` crashes) | scores blank/broken |

**Matches (keep):** login, `/copilot/health`, scenarios list, KG stats, KG impact-subset, upload request/response, doc-detail shape, cost.

---

## 8. Page-by-page audit (condensed; full detail in working notes)

- **Dashboard** (`DashboardPage.tsx:167`): 5 parallel queries; CTAs route-only; rows non-clickable; KPI strip has no loading/error (failures read as 0). **D1** "Open Reviews" = cumulative `total_decisions` (High); **D2** health always emerald + `total_agents`≠active (High); **D3** governance card fabricates `active` (High); **D4/D5** dead timestamps/fields (Med); unpaginated client counts cap at backend limits (Med).
- **Copilot** (`360`): blocking POST mislabeled `streaming` (no SSE consumed; backend `/answer/stream` unused) — **High**; **C1** citation object-vs-array (Critical); **C2** Invalid Date (High); **C3** history reload strips richness (High); sources/agent/memory half-dead (Med); sidebar `hidden lg:flex` kills mobile sessions (Med); orphan bubble on send-fail (Med); modes/summarise/search, feedback, analytics, conversation CRUD unused (opportunity).
- **Research** (`156`): **R1** report contract mismatch — 0 steps/findings, no confidence (Critical); `done` vs `completed`, `tools` absent, findings invisible (High); no Back after select + dead `:reportId` (Med); stale `selected` on error (Med); unclamped depth (Low); rows not keyboard-operable (a11y Med).
- **Documents** (`271`): **O1** hint advertises DOCX/HTML, stack accepts PDF/TXT only (High); **O2/O3** status enums never match backend → Active Jobs always 0, completed amber (High); dead Chunks/Pages/Uploaded columns (Med); no polling/progress (Med); first-file-only drops, no size pre-check (Med); title-substring search over ≤100 (Med); chunks/pages/structure viewers absent (opportunity).
- **KnowledgeGraph** (`145`): **Critical** `label/type` vs `name/entity_type` — entities blank, search/type-counts broken; **no graph visualization at all** (no canvas/SVG/lib; `recharts` dead), relationships never loaded, Dependency card static (backend `/dependency-analysis` unused), impact discards paths/depth; nodes capped 60; no URL state.
- **Compliance** (`379`, local tabs): Assess + Forecast **always 422** (Critical ×2); assessment/forecast/policy/decision shapes mismatch (Critical/High); **inverted Compliance Score** (avg risk ×100 — High); Impact tab decorative with unsupported claims (Med); scales 0–1 vs 0–100 mixed (Med); tabs not keyboard-pattern-complete, no URL sync.
- **Audit** (`150`): **Critical** integrity mismatch — compromised chain still shows "Healthy / 0 broken"; record/evidence/report fields blank or wrong (High); subtitle promises "decision lineage" with no lineage call (High); no filters/pagination/drill-down (Med); reports/evidence errors unrecoverable (Low).
- **Analytics** (`94`): **High** "Total Documents" = `total_invocations`; Usage Trends 3/4 permanently `—`; **zero charts** despite dep + header promises; overview query has no error state; 8 analytics endpoints unused.
- **Agents**: real execute/workflows/collabs/message-bus but **polling mislabeled "Live"**; `runWorkflow` no invalidation; shared pending spinner; per-agent health endpoint unused; role/nav mismatch.
- **Admin**: **read-only** — zero user/role/policy mutations (High gap); roles query has no error state (Med).
- **Settings**: API Base/Key/Density editable with **zero effect** (API Key: High/security-adjacent); rest correctly read-only; theme switch works.
- **Login/Signup**: Signup Rules-of-Hooks violation (High); raw-fetch signup (`[object Object]`); unassociated labels (Med); minimal validation; redirect quirks.

---

## 9. Component audit

12 `ui/` primitives (Button/Card/Badge/Metric/Field/Table/Alert/EmptyState/ErrorState/Skeleton/ProgressBar/ToastViewport) are genuinely reused and consistent; `ProtectedRoute`/`RequireRole` correct-but-thin (no redirect on deny, emoji lock). **Issues:** `CardBody` exported but pages hand-roll `.card-body`; `Badge md` has no class; `Alert danger` uses `role="status"` not `alert`; `ProgressBar aria-valuenow` unclamped; `EmptyState h3` regardless of hierarchy; `ToastViewport` danger toasts `role="status"`; `NotFoundPage` nests `<Link><Button>` (invalid); `Card interactive` + `EmptyState/ErrorState action` slots never used (dormant, info).

---

## 10. Design-system audit

**Verdict: one intended system, two local divergences.** Tokens real (`tailwind.config`: brand blue, surface light/dark, Inter + JetBrains Mono, `elevated/glow` shadows, xl/2xl radii; `index.css` centralizes card/btn/input/badge/skeleton/nav); dark mode real (`class` strategy, all components/pages have `dark:` variants). **Divergences:** Signup uses alien palette + nonexistent `text-text-*` tokens + `rounded-lg` vs system `rounded-2xl` (Med); hand-rolled auth error boxes vs `ErrorState` (Low); emoji/glyph icons vs AppShell SVG set (Low). No form/i18n/a11y deps installed.

---

## 11. Interaction audit

Real: routing, tabs (local state), forms, toasts, polling, optimistic copilot echo, upload, run buttons, session switching. **Dead/fake:** sidebar toggle; Profile/API Keys/Activity Log; SystemStatusPill; Settings Base/Key/Density; "Live" message bus (5s poll); Copilot "streaming" (blocking POST); Impact tab cards; Governance "View all →" misroute; suggestion chips fill-but-don't-send. **Missing:** retries on reports/evidence/scenarios errors; send retry; delete/rename sessions; drill-downs everywhere; pause on auto-refresh.

---

## 12. Responsive audit

Grids collapse correctly on all pages; tables saved by `overflow-x-auto` (scroll, no breakage). **Structural gaps:** shell never collapses — fixed `w-64` sidebar + dead toggle squeeze phones; Copilot sessions unreachable <`lg`; Documents 7-col table scrolls with no card fallback; no sticky headers. No overflow breakage found beyond sidebar squeeze.

---

## 13. Accessibility audit (blockers)

Signup hook-order crash risk (High); unassociated signup labels (Med); `<li onClick>` report rows + tab lists without keyboard pattern (Agents/Compliance/Audit tabs, Med); color-only statuses/deltas/pill (Med); `View all →` ×4 with no aria-label (Low-Med); tables lack captions/scope (Low); skeleton shimmer + spins ignore `prefers-reduced-motion` (Low); auto-refresh with no pause/announce (Low). Positives: focus-visible ring, `role=alert` errors, `role=log` copilot, labelled search, Esc-dismiss toasts, UserMenu aria.

---

## 14. State-management audit

No global store; ~30 React Query keys, all per-page (same endpoint under different keys → Dashboard↔page navigation refetches: overview, documents, reports, gov-stats; triple health truths). Local-state mirrors query cache (Copilot messages, Research/Compliance `selected`, agent `output`) → stale snapshots. **Missing invalidations:** forecastRisk (none — High), copilot messages after send (High), runWorkflow (Med), upload misses dashboard keys (Med). Over-broad `["agents"]` invalidation storms 5 keys incl. 5s bus (Med). Auth triple-store (state + localStorage + module token) desyncs on reload. Dead `scheduleRefresh`; sentinel `"none"` keys; discarded health query.

---

## 15. Performance audit

Route splitting exists (13 lazy routes) but shell eager + double Suspense. **Bundle tax (High):** `recharts` (~300KB+, zero imports) + `date-fns` (zero imports) ship; **ReactQueryDevtools ships to prod unconditionally** (High). No virtualization — full-fetch + `.slice()` everywhere (latent cliff at 1k+ rows). Re-render amplifiers: Toast provider wraps app (every toast re-renders root), Health/Theme fresh object literals, Copilot index-keys + unmemoized bubbles, inline per-keystroke filters. Polling fan-out up to 6 timers incl. 5s bus, no background-pause. StrictMode double-refresh races rotation. Graph page renders no graph (perf upside today; viz later needs canvas + code-split).

---

## 16. Test coverage audit

8 suites, all under `src/test/`, zero colocated; **no MSW** — canned `fetch` per test. `format` suite is the only strong one. `api.test` asserts passthrough fields, never URL/method/headers/body. `pages.test` renders 10 pages against generic `{status:"ok"}` (proves nothing; passes with backend down); **Documents + Analytics have zero tests**; Login/Signup flows untested. `integration.test` renders only ToastViewport (misnamed). A11y suite covers Sidebar landmarks only, concedes RBAC untested. **High-risk untested:** auth refresh/login/logout/roles, upload+409, copilot send/invalidation, all run-mutations, `lib/api` contract, health fallback, focus/keyboard paths. Green suite ≠ working app.

---

## 17. Configuration audit

`package.json` scripts sane (`dev/build/build:static/preview/lint/typecheck/test`). **Risks:** `recharts`+`date-fns` unused (High); devtools in `dependencies` + always mounted (High); **committed `tsc -b` artifacts shadow live configs** (`vite/vitest/tailwind.config.js` + `.d.ts` beside `.ts`; Tailwind may resolve stale `.js` — Med); `SPA_BASE` vs `VITE_BASENAME` pair must be set together (High when touched); sourcemap gate trusts `NODE_ENV` not Vite mode (bare builds leak sources — Med); prod API URL baked at build + Settings implies runtime config that doesn't exist (Med); `.eslintrc` loads react-hooks with **empty rules** (stale-closure bugs unenforced — Med); `Dockerfile.production` context-sensitive COPYs + healthcheck probes `/` not `/app` or `/health` (Med); `dist/` carries stale `hero-3d.js`/`importmap.json` the assembler doesn't clean (Low-Med); `index.html` absolute `/favicon.svg` 404s under `/app` (Low).

---

## 18. User workflow map (actual, with breaks marked)

1. **Landing → Login → Dashboard**: `→/app/login→POST login→/`. ✗ deep-link query/hash dropped; ✗ signup always `/`.
2. **Dashboard → Copilot → Answer → Citation**: works until citations render ✗ (C1 object-vs-array), history reload strips richness ✗ (C3), no source navigation ✗.
3. **Dashboard → Documents → Upload → Ingestion**: upload works (PDF/TXT only ✗ advertised DOCX/HTML); toast says "processing" ✗ (always); progress invisible ✗ (no polling); Active Jobs permanently 0 ✗; completed renders amber ✗.
4. **Documents → Knowledge Graph**: no link; KG entities blank ✗ (label/type); no edges; impact works on IDs only.
5. **Dashboard → Research**: run works; report renders 0 steps/findings, no confidence ✗; trapped (no Back) ✗; no deep link ✗.
6. **Dashboard → Compliance**: Assess ✗ 422; Forecast ✗ 422; policies/decisions tables wrong ✗; score inverted ✗; Impact tab static ✗.
7. **Dashboard → Audit**: lists render with blank columns ✗; integrity always Healthy ✗ (tamper-evidence false); no drill-down ✗.
8. **Dashboard → Analytics**: tables render; Total Documents mislabeled ✗; 3/4 trend tiles `—` ✗; no charts ✗.
9. **Dashboard → Agents**: execute works if capability enum matches ⚠ (422 risk on free capability); workflows create ✗ 422 (flat steps); run returns `run_id` read as `execution_id` ✗; "Live" is 5s polling.
10. **Admin**: view-only; `member_count`/nested stats undefined ✗.
11. **Settings**: theme works; Base/Key/Density fake ✗.

---

## 19. Functional bugs (consolidated, Critical/High only)

F1 Signup `useState`-after-return (crash risk) — `SignupPage.tsx:8-15`. F2 Copilot citations object-vs-array (dead/crash) — `CopilotPage.tsx:233,262,349` vs `schemas/copilot.py:94`. F3 Research report shape (0 steps/findings, no confidence) — `ResearchPage` vs `schemas/research.py:111-128`. F4 Assess + Forecast always 422 (`extra=forbid`) — `complianceApi.ts:13-15`, `riskApi.ts:16-22`. F5 Workflow create 422 (flat steps, missing `graph`) + `run_id` misread — `agentApi.ts:41-47`. F6 Audit integrity always Healthy — `AuditPage.tsx:53-56` vs `audit.py:110-125`. F7 KG entities blank (`label/type`) — `KnowledgeGraphPage` vs `schemas/knowledge_graph.py:47-61`. F8 Admin shapes (overview/stats/users/roles) — `AdminPage` vs `schemas/admin.py`. F9 Ingestion `job_id/status/epoch` vs `run_id/13-enum/ISO` — `DocumentsPage` vs `schemas/ingestion.py`. F10 Conversations ISO vs epoch + missing preview/count — `CopilotPage.tsx:172` vs `schemas/conversation.py`. F11 Refresh drops `user` (typed required) — `authApi.ts:39` vs `security/api.py:434`. F12 Health `components[]` vs `checks{}` map — `healthApi.ts:9-15` vs `health.py:67-91`. F13 Governance policy/decision/stats shapes — `CompliancePage` vs `schemas/governance.py`. F14 Forecast/trend shapes (`projected_score`, array-vs-object) — `riskApi` vs `schemas/forecasting.py`. F15 Alerts/changes/recommendations/review shapes — `analyticsApi` vs respective schemas. F16 Forecast-risk + copilot-messages missing invalidations (stale UI) — `CompliancePage.tsx:181`, `CopilotPage.tsx:47-50`. F17 "Open Reviews" = cumulative total; health always green — `DashboardPage.tsx:34-53`. F18 "Total Documents" = invocations — `AnalyticsPage.tsx:41-44`. F19 Compliance Score inverted — `CompliancePage.tsx:73-75`. F20 Sidebar collapse + hamburger dead; shell never collapses — `App.tsx:26,28`.

---

## 20. UX problems (top)

- Silent-zero KPIs (no loading/error on strips: Dashboard/Analytics/Governance) — users can't distinguish outage from zero.
- Dead affordances in account surface (Profile/API Keys/Activity Log) + fake Settings editables.
- Trapped flows: report select unmounts list (no Back); send-fail orphans bubble (no retry); denied roles stall on "Access restricted".
- Mobile: sessions unreachable, sidebar squeeze, tables scroll without fallback.
- Feedback gaps: toasts-only errors, silent logout, no pause on auto-refresh, no focus management on new messages.
- Trust surfaces lie: SystemStatusPill, "Live" bus, "Streaming", "Recent Governance Actions", inverted score.

---

## 21. Integration problems

No 401 recovery (timer-only refresh vs expiring tokens); no timeouts/cancel on long POSTs; split-brain HTTP clients (3 error shapes); unencoded IDs; POSTs with wrong/missing bodies (workflow, impact, assess, forecast); UUID-strict doc routes (non-UUID → 422); `res.ok` tolerates 201 correctly (fine); prod JWT required on `/health/ready` + `/me` (frontend health fallback handles 401 correctly); demo `Bearer demo` sent to backend in demo builds; converter gaps epoch↔ISO on 6+ surfaces.

---

## 22. Misleading UI (register)

"Pending governance decisions" (cumulative); health always emerald; "agents active" (registered); "Recent Governance Actions" (static counters); "Total Documents" (invocations); inverted Compliance Score; "Active Jobs 0" (enum mismatch); completed-amber jobs; "Upload → processing" (always); "Live" bus (poll); "Streaming" (blocking); DOCX/HTML hint; "Usage Trends" (4 divs); tamper-"Healthy"; "View all → Governance" (→/compliance).

---

## 23. Dead/no-op interactions (register)

Sidebar toggle; Profile/API Keys/Activity Log; Settings Base/Key/Density; health query (fetched, discarded); suggestion chips (fill only); Impact tab cards; 19 dead service fns (§6); `getExecution`/`getAgentHealth`/`getDocumentChunks/Pages` detail paths; conversation CRUD (delete/rename/trim/context); feedback thumbs; mode switches; agent rows (no latency drill-down); `Card interactive`/`action` slots.

---

## 24. Missing functionality (vs backend capability)

Logout/revoke endpoint; streaming (`/answer/stream`); feedback loop; conversation CRUD + filters; research plan-only/stats/filters/kind; doc chunks/pages/structure/hierarchy viewers + metadata PATCH + ingestion scheduler/stats; KG relationships/dependency-analysis/viz; lineage UI; report generation; alerts/recommendations/review surfaces; cost/leaderboard/latency analytics; admin mutations (users/roles/policies); workflow status tracking; runtime API-base config.

---

## 25. Product-priority map

- **TIER 1 (core value):** Copilot (answer→citation→verify), Documents (upload→indexed→inspectable), Dashboard (truthful glance).
- **TIER 2 (workspace):** Research (grounded reports), Knowledge Graph (entities→impact→viz), Compliance (assess/forecast that don't 422).
- **TIER 3 (operational):** Audit (tamper-evident drill-down), Analytics (real charts, correct labels), Agents (execute/track honestly).
- **TIER 4 (administrative):** Admin (mutations), Settings (real persistence), Auth pages (correctness + a11y).

---

## 26. Recommended redevelopment stages

Default order stands with two adjustments: **Auth correctness first** (blocking: hooks bug, refresh/401, roles) and **contract-type regeneration before any page work** (every page is broken by DTO drift). Recommended:

- **STAGE 2 — Foundation:** OpenAPI-generated types + contract tests (breaks the drift cycle); HTTP client (401-refresh queue, timeouts, cancel, one error shape); env/config single-source (`SPA_BASE`/`VITE_BASENAME`, runtime API URL); remove `recharts`/`date-fns`/devtools-from-prod or wire lazily; delete `tsc` shadow configs.
- **STAGE 3 — Auth:** fix Signup hooks; server logout+revoke; HttpOnly-cookie or documented token strategy; `getMe` revalidation; `roles/rbac_roles` normalize; redirect-with-full-location; session-expired UX.
- **STAGE 4 — Shell:** collapsible/drawer nav; role/link parity (`/agents`); guard `*`; live SystemStatusPill; kill dead menu items or route them; mobile nav.
- **STAGE 5 — Design system:** unify Signup/Login; `role=alert` discipline; keyboard tab patterns; color+text statuses; reduced-motion; table captions/scope.
- **STAGE 6 — Dashboard:** truthful KPIs (server counts, loading/error states), clickable rows, correct governance/health.
- **STAGE 7 — Copilot:** citation adapter (`references[]`), real streaming or honest pending+cancel, history hydration, source navigation, feedback, conversation CRUD, error/retry UX.
- **STAGE 8 — Documents:** contract-aligned statuses/timestamps, polling/progress, chunk/page inspectors, server search/filter/pagination, honest type hints.
- **STAGE 9 — Knowledge Graph:** adapter (`name/entity_type`), relationships + real viz (new dep, code-split), depth controls, URL state.
- **STAGE 10 — Research:** contract-aligned report render (steps/key_findings/citations), Back + `:reportId` deep link, progress, kind/context.
- **STAGE 11 — Compliance:** valid assess/forecast payloads, correct score direction, policy/decision adapters, real Impact tab, tab URL sync.
- **STAGE 12 — Audit:** integrity adapter (never false-Healthy), record detail → evidence → lineage drill-down, filters/pagination, report actions.
- **STAGE 13 — Analytics:** correct metrics, real charts (or drop claims), wire unused endpoints or delete, pause-able refresh.
- **STAGE 14 — Agents:** honest polling labels, execution tracking (`run_id`), workflow graph-shape create, status invalidation.
- **STAGE 15 — Admin:** user/role mutations, error states, permission model.
- **STAGE 16 — Settings:** persist what persists (theme), read-only-ify the rest or wire runtime config.
- **STAGE 17 — Cross-cutting QA:** invalidation matrix, pagination/virtualization, a11y pass, responsive pass, MSW-based tests replacing smoke tests.

---

## 27. Dependency order

Contract types + HTTP client → Auth → Shell → Design system → Tier-1 pages (Dashboard, Copilot, Documents) → Tier-2 (Research, KG, Compliance) → Tier-3 (Audit, Analytics, Agents) → Tier-4 (Admin, Settings) → QA. No page stage can start before STAGE 2 (DTO drift breaks all of them); Auth (3) blocks shell role work (4); design system (5) blocks page rebuilds cosmetically but pages can proceed structurally in parallel after 2–4.

---

## 28. Risks that must be addressed before implementation

1. **DTO drift has no backstop** — without generated types + contract tests, any rebuild re-drifs. Gate: Stage 2 first, CI contract check.
2. **Auth threat model** — localStorage refresh + demo kill-switch + no revocation. Decide token strategy before building on it.
3. **Silent-false trust surfaces** (integrity "Healthy", green pill, inverted score) — triage order must fix lies before polish.
4. **Test suite gives false confidence** — MSW + URL/method/state assertions required before trusting green.
5. **Backend `extra=forbid` + enums** — five mutations 422 today; payloads must be built from backend schemas, not frontend guesses.
6. **Bundle/prod hygiene** — devtools, recharts, sourcemaps, shadow configs will ship again unless removed in Stage 2.
7. **Timestamp chaos** (epoch vs ISO × 6 surfaces) — normalize in adapters with explicit unit handling.
8. **Scope creep magnets** — Impact tab, Dependency card, "trends" header promise features with no backend/UI wiring; explicitly descoped until their stages.

*End of Stage 01 audit. No code modified. Next: STAGE 02 (foundation) only after sign-off on this blueprint.*
