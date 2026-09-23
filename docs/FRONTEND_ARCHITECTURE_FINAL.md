# RegIntel AI — Frontend Architecture (Final)

## 1. Application structure
`src/`: `pages/` (14 routes), `services/api/` (one module per backend
domain, all through `lib/api.ts`), `types/api/` (backend-mirror DTOs),
`adapters/` (DTO→view transforms), `lib/` (query keys, config, format,
dates, errors), `components/ui/` (Stage-05 primitives + ErrorBoundary),
`providers/` (theme, health, toast, auth), `test/` (MSW suites).

## 2. Route architecture
`/login`, `/signup` public; everything else behind `ProtectedRoute` with
`RequireRole` derived from the same `ROUTE_ROLES` map as sidebar
visibility. Deep links: `/copilot/:conversationId`,
`/research/:reportId`, `/knowledge-graph/:nodeId`. Unknown paths render
`NotFoundPage` behind auth. Lazy-loaded pages with suspense fallback.

## 3. Auth/session architecture
State-machine provider: unknown → bootstrapping (refresh + `/me`
revalidation) → authenticated/unauthenticated, fail-closed. Access token
memory-only; refresh token in localStorage; single-flight 401 handling;
no refresh loops; logout is local cleanup + navigation (no backend revoke
endpoint exists). Demo mode requires explicit `VITE_AUTH_ENABLED=false`
and refuses production builds.

## 4. API/client architecture
Single `api` transport (`get/post/put/patch/del`) with base URL + `/api/v1`
prefix, timeouts (including `LONG_TIMEOUT_MS` for blocking runs), 401
single-flight refresh, `encodePathSegment` on every dynamic path, safe JSON
handling. No axios, no raw fetch, no per-page clients.

## 5. Query/cache architecture
Canonical `*Keys` factories per domain; every server parameter in its key;
detail-on-demand; mutations invalidate only affected prefixes; no polling
except bounded ingestion runs (Documents) and manual refresh buttons
elsewhere. Default `staleTime` 30s, no refetch-on-focus.

## 6. Design-system architecture
Tokens + primitives (`Card`, `Badge`, `Button`, `Metric`, `Skeleton`,
`ErrorState`, `EmptyState`, `Table`, `Tabs`, `Field`, `Alert`,
`ErrorBoundary`); page headers (`page-title`/`page-description`);
`meta-text` microcopy; dark mode via class strategy. No custom hex in
pages; no competing implementations.

## 7. Domain/page ownership
- Dashboard → system overview (current-state aggregates + manual refresh).
- Copilot → evidence-grounded interactive Q&A (blocking, abortable).
- Documents → ingestion/indexing lifecycle with bounded polling.
- Knowledge Graph → exploration, reachability, dependencies (SVG, no lib).
- Research → synchronous reports with deep links.
- Compliance → assessments/forecasts/policies/decisions workbench.
- Audit → traceability with tri-state hash-chain integrity.
- Analytics → current-state agent operations (no history invented).
- Agents → registry/coordination/workflows/messages (all blocking).
- Admin → users/roles/permissions/platform settings (no admin-only claims).
- Settings → identity display, browser-local theme, sign-out, references.

## 8. Cross-page navigation
Deep links (copilot/research/KG), audit↔evidence/record cross-tab jumps,
report ref jumps, admin→settings boundary links, settings→admin links.
Selection state is page-local; switching resources never shows stale detail;
404 never substitutes another resource.

## 9. Error-state architecture
Per-region `ErrorState` + retry with backend messages; `role=alert` on
failures; `role=status` on pending runs; 401/403 titled distinctly;
transport vs domain-failure vs validation vs 404 kept separate; root
`AppErrorBoundary` preserves navigation on unexpected render crashes.

## 10. Accessibility strategy
One h1 per route; captioned/scoped tables; keyboard tabs/drawer/menus;
labelled controls; text-first statuses (never color-only); announced
loading/error states; accessible names on icon/copy/destructive buttons.

## 11. Responsive strategy
Single-column stacking with multi-column only where hierarchy supports it;
horizontally scrolling tables; truncating IDs/hashes with full-value
titles; verified 390/768/1024/1440 per stage (ds6–ds17 screenshot sets).

## 12. Security boundaries
Backend is the authorization boundary (middleware auth; no per-route admin
gates — stated openly). Frontend never renders tokens, hashes, secrets, or
passwords; secret settings masked end-to-end; free-form dicts render
scalars only; no `dangerouslySetInnerHTML`; VITE_* values are public config
only. Precise claim: the frontend does not render secret values — not
"the system is secure".

## 13. Testing strategy
MSW suites per domain with backend-shaped fixtures; contract tests lock
endpoint/payload shapes; architecture-truth tests guard invariants
(fail-closed integrity, no fake trends, blocking execution, UX-only role
gates, local-only theme); smoke tests per page; a11y/shell/format/unit
suites. Infra: 5s async tolerance, 2 workers for determinism.

## 14. Build/deployment strategy
Vite build with per-page code splitting (3–35KB/page); `/app` base with
`ROUTER_BASE` agreement documented; SPA fallback assumed; dev-only
devtools excluded from production; no test code in runtime bundles;
`landing/` frozen and untouched by all frontend stages.

## 15. Known backend limitations
In-memory stores (restart resets) across analytics/agents/admin/audit;
no logout/revoke, profile, password, session, notification, locale, or
preference APIs; no per-route admin gates; no history series for trends;
retrieval-analytics platform unused (DB-bound, untyped reads); automation
workflow lifecycle without a dedicated surface; secret values readable by
any authenticated caller.

## 16. Deferred capabilities
Lineage DAG, policy rule-builder CRUD, decision registration, review/alert
workflows, report export, history retention, per-agent cost breakdown,
bulk operations, sessions/MFA, maintenance controls, provider management.
