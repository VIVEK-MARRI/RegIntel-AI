# Agents Architecture - STAGE 14

## 1. Product purpose
An operational control surface for the agent framework: which agents are
registered and what they declare, deterministic coordination runs, reusable
orchestration workflows with blocking runs, and the message bus. No live
badges, no polling, no autonomous-agent language.

## 2. Actual agent domain model
- **Agent** (`AgentMetadata`): name, description, version, author, declared
  `capabilities[]` (kind enum + name + description), lifecycle `status`
  (registered|active|busy|paused|failed|disabled), default retries/timeout,
  priority, tags, timestamps. Capabilities are registry-declared facts —
  the execute form only offers the selected agent's set.
- **Health** (`AgentHealthCheck`): point-in-time booleans and counters with
  last error/success/failure times — no thresholds invented.
- **Result** (`AgentResult`): status (pending|running|succeeded|failed|
  timed_out|retrying|cancelled), attempts, durations, error, output dict.
- **Coordinator** (`CoordinatorResult`): query, selected agents, per-step
  `AgentResult[]`, scalar final output, status, duration, conflicts, notes.
  The plan's step internals are NOT echoed back — only results render.

## 3. Agent registry implementation
`GET /agents/agents` with server filters (capability enum, text, tag,
paging) → envelope (unwrapped, short-page heuristic). Detail
`GET /agents/agents/{name}` + health `GET .../{name}/health` load on
selection; unknown names 404 into an error panel, never a substituted agent.
Registration (`POST /agents/agents`) creates the backend's metadata/echo
agent — the form says exactly this. Removal (`DELETE`) needs two clicks.

## 4. Actual workflow model
Orchestration definitions (`WorkflowDefinition`): name, description, graph
with steps (`step_id`, `agent_name` required, capability string, description,
`depends_on` step IDs, timeout/retries) and mode
(sequential|parallel|pipeline|dynamic). Client assigns step IDs at creation
so dependencies reference real IDs. Runs (`AgentWorkflow`): `run_id`,
status (pending|running|succeeded|failed|partially_succeeded|cancelled|
timed_out), durations, error, and the embedded orchestration result with
per-agent contributions.

## 5. Actual execution lifecycle
ALL execution is blocking (pattern A — verified with `await` at every
service call site):
- `POST /agents/execute` awaits the handler → `AgentResult`.
- `POST /agents/coordinate` plans + distributes + executes → full result.
- `POST /agents/workflows/{id}/run` awaits orchestration → full run.
"Running" renders only while the request is in flight; duplicate submits are
disabled; transport 200 with a failed domain status renders as failure.
NO polling, NO run_id+status loop, NO streaming, NO cancellation endpoint
(the automation `/workflow/*` cancel belongs to the deferred lifecycle
surface, §17).

## 6. Task planning/routing semantics
`TaskPlanner` is "intentionally deterministic and dependency-free" (service
docstring): requested capabilities — or keyword inference (search/find→
retrieval, risk/compliance→risk_assessment, etc., else reasoning) — become
ordered steps with per-step retry/timeout hints; agents are matched by
declared capability at distribution. UI language: "deterministic routing",
never autonomous/LLM-driven/emergent.

## 7. Agent orchestration semantics
Each run executes the definition's graph and returns per-agent contributions
with statuses; the message bus records inter-agent traffic retrievable with
from/to/limit filters (in-memory, last-N order, manual refresh). The fuller
`/agents/orchestrate` surface (evidence store, consensus) is deferred (§17).

## 8. Endpoint inventory
Verified in `app/api/v1/{agents,orchestration,intelligence_agents}.py`
(+ contract-tested registry/execute/workflow shapes).

| Method | Path | Use | Notes |
|---|---|---|---|
| GET | `/agents/agents` | Registry | capability/text/tag/page filters; envelope |
| GET/DELETE | `/agents/agents/{name}` | Detail / remove | 404 when unknown |
| GET | `/agents/agents/{name}/health` | Snapshot | 404 when unknown |
| POST | `/agents/agents` | Register (201) | Metadata/echo agent (backend docstring) |
| POST | `/agents/execute` | Blocking run | Enum capability + dict input; LONG timeout |
| POST | `/agents/coordinate` | Blocking plan+run | query + desired caps + max_steps 1–32 |
| GET | `/agents/workflows` | Bare-array definitions | Stored order |
| POST | `/agents/workflows` | Create (201) | Requires `graph` (422 otherwise, tested) |
| POST | `/agents/workflows/{id}/run` | Blocking run | Optional `{query}`; 404 when unknown |
| GET | `/agents/messages` | Bus history | from/to/limit; manual refresh only |
| GET | `/agents/collaborations` | Bare-array calls | No filters server-side |
| GET | `/agents/executions/{id}` | NOT USED | Untyped dict; no list endpoint to discover ids |

## 9. Request/response contracts
Create-workflow sends exactly `{name, description?, graph: {mode, steps[]},
tags?, version?}` with client-assigned step IDs. Execute sends
`{agent_name, capability(enum), input(object), max_retries?, timeout_ms?}`
with client-side JSON validation (never raw strings). Coordinate sends
`{query, desired_capabilities[], max_steps}`. All responses render field by
field; `output`/`payload`/`final_output` dicts show scalar entries only.

## 10. Query/cache architecture
`agentsKeys`: `list(params)` (every filter + page in the key), `agent(name)`,
`agentHealth(name)`, `workflows()`, `messages(params)`, `collaborations()`.
Detail/health load on selection; messages refetch on filter change or manual
refresh. No polling intervals anywhere (the old 30s/15s/5s timers are gone).

## 11. Mutation/invalidation rules
- Register/remove → invalidate the `["agents","list"]` prefix only.
- Create workflow → invalidate `workflows()` only.
- Execute/coordinate/run → NO invalidation (results render from the
  authoritative response; nothing stored server-side changes for lists).
- No optimistic updates for execution state; no cross-domain invalidation.

## 12. Loading/error/empty states
Independent Skeletons; ErrorState+Retry with backend messages, distinguishing
transport failure ("request failed"), domain failure ("execution failed"
with backend status+error), validation (client JSON/zip errors + backend
422s), and 404s. Duplicate-submit buttons disable while pending. Empty states
for registry/workflows/messages/collaborations/results.

## 13. Security boundaries
Stage-02 client; ids path-encoded; no raw fetch/tokens; capability JSON
parsed before send; free-form dicts render scalars only; registration and
removal surface backend behavior honestly (echo agents; immediate removal
with two-click confirm); backend remains the authorization boundary (no
role gates found on these routes — actions shown, not theater-hidden).

## 14. Accessibility
One h1 ("AI Agents" kept for the existing page test); Stage-05 Tabs with
roving keyboard support; labelled inputs/selects/checkboxes; statuses as
text badges (never color-only); pending regions `role=status`; errors
`role=alert`; capability toggles use `aria-pressed`; step numbers are
decorative (`aria-hidden`) beside real headings.

## 15. Performance
Paged registry; detail/health on selection; no per-row prefetch; messages
bounded by server limit with scroll; no polling timers; mutation-scoped
invalidation.

## 16. Backend limitations
- Everything is in-memory: registry, bus, and orchestration definitions
  reset with the backend; messages keep last-N only.
- Coordinator echoes results, not the plan's step internals.
- `/executions/{id}` is unusable without a discovery path.
- Automation `/workflow/*` lifecycle (pause/resume/cancel/tasks/audit) is a
  separate surface, intentionally untouched here (§17).
- Invalid lifecycle transitions raise server-side (500); the UI gates
  actions by status but surfaces backend errors verbatim.

## 17. Deferred capabilities
Automation workflow lifecycle/tasks/audit UI; `/agents/orchestrate` with
evidence/consensus views; decision-lineage rendering; policy-gated action
visibility (if backend RBAC lands); bulk operations; run history beyond the
in-memory window.
