# Final Frontend QA — STAGE 17

## Consistency matrix

| Area | Status | Evidence | Remaining limitation |
|------|--------|----------|----------------------|
| Authentication | Pass | Stage-03 state machine untouched; bootstrap fail-closed, single-flight 401, memory-only access token verified by code read; demo flag fails closed in prod builds | Backend limitation: no logout/revoke endpoint (logout is local cleanup, stated in UI) |
| Authorization | Pass | No per-route role gates exist backend-side (verified in `admin.py` + middleware); UI states this openly; route guards kept as UX | Backend limitation: any authenticated identity can call admin mutations |
| API contracts | Pass | `api-contracts.test.tsx` green; single `lib/api.ts` transport; universal `encodePathSegment`; no axios/raw fetch | Intentional: untyped `Dict` reads on retrieval-platform/retry endpoints excluded from UI |
| Dashboard | Pass, 1 fix | "Live operational state" → "Current operational state"; insight score `42%` → `0.42` (0–1 share, no test locked the old format) | None (product decision: delivery_rate % kept — it is a genuine rate) |
| Copilot | Pass, 1 fix | Memory relevance `NN%` → `score 0.90 (0–1 relevance)`; sr-only h1 added (smoke test updated to heading query) | Intentional: confidence/faithfulness % retained — test-backed Stage-07 semantics |
| Documents | Pass | Bounded ingestion polling only; verified visually at 390/1440 | None |
| Knowledge Graph | Pass | Direction-preserving edges; deep links tested; 4-width shots exist | None |
| Research | Pass | No-substitution deep links tested | None |
| Compliance | Pass | Risk bands/direction tested; forecast confidence intentionally unshown | None |
| Audit | Pass | Integrity tri-state tested incl. fail-closed malformed case | Backend limitation: `invalid=max(total,1)` quirk shown as-is |
| Analytics | Pass | No-history → no-chart tested | Backend limitation: current aggregates only |
| Agents | Pass | Blocking execution, no polling, deterministic routing tested | Backend limitation: in-memory stores; automation `/workflow/*` surface deferred |
| Admin | Pass | No admin-only claims; secrets/hashes never render (tested) | Backend limitation: no per-route admin gate; no self-delete guard |
| Settings | Pass | Theme local-only tested; unsupported items named, not tabled | Backend limitation: no profile/password/session/notification APIs |
| Navigation | Pass | Route inventory verified; sidebar-links-to-routes test exists; unknown paths → NotFound behind auth | None |
| Responsive | Pass | ds17 login/dashboard/copilot/documents at 390+1440 join ds6–ds16 full-width sets; zero page overflow | Pre-existing pattern: 390 tab strips scroll internally (shared `.tabs`) |
| Accessibility | Pass | h1 on every route (Copilot sr-only + NotFound h1 fixed this stage); tables captioned/scoped; tabs keyboarded; status/error roles | None |
| Performance | Pass | Page chunks 3–35KB; no polling except bounded ingestion; no per-row prefetch; lazy routes | None |
| Security | Pass | Sweeps below; no credential exposure; backend remains authority | Backend limitation: secret *values* readable by any authenticated caller (UI masks only) |
| Testing | Pass | 419/419 ×2 consecutive full runs; contract tests green | Test-infra: `asyncUtilTimeout` 5000 + 2 workers (documented, no product impact) |
| Build/deployment | Pass | Clean build; dev-only devtools lazy; no test imports in runtime; VITE_* all public config; base-path documented | Deployment limitation: SPA fallback + `/app` base per hosting (pre-existing docs) |

## Sweeps performed (all read-only unless a fix is listed)
- Terminology: hits were all "never-X" documentation comments — no live violations; fixed Dashboard "Live" + Copilot relevance %.
- Fallbacks (`?? 0` etc.): all in count-aggregation contexts with correct zero semantics.
- Fail-closed: integrity (fail-closed tested), health unknown-on-zero, shares show "no invocations", no `undefined → healthy` anywhere.
- Secrets: only guarded handling + fixtures; secret masking tested.
- XSS: no `dangerouslySetInnerHTML`, no markdown pipeline, no raw fetch; scalar-only dict rendering intact.
- Paths: universal `encodePathSegment` in services.
- Auth duplication: none (provider-only token handling).
- Forms: one vague label found ("Send" on chat input — correct as-is, unchanged).
- Empty states: no bare "No data" anywhere.
- Errors: no generic "Something went wrong"/"Failed" titles.
- Dead code removed: `adapters/audit.ts`, `adapters/views.ts`, `toAdmin*View` exports, 3 dead query keys.
- Debug code: only intentional eslint-disabled auth logging; no TODO/FIXME introduced.

## Fixes applied in this stage
1. `CopilotPage.tsx`: memory relevance `%` → 0–1 share + sr-only h1.
2. `DashboardPage.tsx`: "Live" → "Current"; insight score → 0–1.
3. `NotFoundPage.tsx`: h2 → h1.
4. `App.tsx` + new `ErrorBoundary.tsx`: shell-preserving crash fallback with route-change reset (+3 tests).
5. Deleted dead adapters/keys listed above.
6. `pages.test.tsx`: Copilot smoke test uses heading role.
7. Test infra: async tolerance + worker bound (stability fix, verified 419×2).

## Journeys walked (code + visual)
Login → dashboard → documents → audit; copilot conversation render;
research/compliance/agents/admin detail-selection semantics (selection never
survives a resource switch; 404 never substitutes); settings theme persists
across reload; sign-out → login. No defects found beyond items above.
