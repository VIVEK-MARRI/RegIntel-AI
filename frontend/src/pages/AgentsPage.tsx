import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Input, Select, TextArea } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/providers/ToastProvider";
import { formatDurationMs, formatNumber, formatRelative, truncate } from "@/lib/format";
import { agentsKeys } from "@/lib/queryKeys";
import {
  coordinate,
  createWorkflow,
  executeAgent,
  getAgent,
  getAgentHealth,
  getAgentMessages,
  getAgents,
  getCollaborations,
  getWorkflows,
  registerAgent,
  runWorkflow,
  unregisterAgent,
} from "@/services/api/agentApi";
import type {
  AgentCapability,
  AgentHealthCheck,
  AgentMetadata,
  AgentResult,
  AgentWorkflow,
  CapabilityKind,
  CoordinatorResult,
  WorkflowGraphStep,
} from "@/types/api/agents";

/**
 * Agent operations workspace: registry, deterministic coordinator,
 * orchestration workflows, and the message bus.
 *
 * Backend-verified execution semantics (no polling, no live badges):
 * - POST /agents/execute, POST /agents/coordinate, and
 *   POST /agents/workflows/{id}/run are all BLOCKING: the backend awaits
 *   completion and returns the full result. "Running" shows only while the
 *   request is in flight.
 * - The coordinator planner is intentionally deterministic (keyword →
 *   capability mapping); the UI calls it rule-based routing, never
 *   autonomous planning.
 * - HTTP 200 transport success is NOT workflow success: every result panel
 *   leads with the backend domain status.
 * - The message bus is in-memory history with from/to/limit filters and a
 *   manual refresh — no live stream exists.
 */

type TabId = "agents" | "coordinator" | "workflows" | "messages";

const TABS = [
  { id: "agents" as const, label: "Agents" },
  { id: "coordinator" as const, label: "Coordinator" },
  { id: "workflows" as const, label: "Workflows" },
  { id: "messages" as const, label: "Messages" },
];

const CAPABILITIES: CapabilityKind[] = [
  "retrieval", "reasoning", "summarization", "classification",
  "extraction", "risk_assessment", "recommendation", "forecasting",
  "knowledge_graph", "change_detection", "impact_analysis", "alerting",
  "audit", "governance", "workflow", "review", "compliance",
  "orchestration", "other",
];

const EXEC_MODES = ["sequential", "parallel", "pipeline", "dynamic"];
const AGENT_PAGE_SIZE = 50;

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
function statusTone(s: string): Tone {
  switch (s) {
    case "active":
    case "succeeded":
    case "completed":
    case "healthy":
      return "success";
    case "busy":
    case "running":
    case "in_progress":
    case "retrying":
    case "degraded":
      return "info";
    case "paused":
    case "partially_succeeded":
    case "timed_out":
      return "warning";
    case "failed":
    case "error":
    case "unhealthy":
      return "danger";
    default:
      return "neutral";
  }
}

/** Runtime guards: backend shapes are trusted but never assumed. */
function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function scalarEntries(v: unknown): [string, string][] {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return [];
  const out: [string, string][] = [];
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (typeof val === "string" || typeof val === "number" || typeof val === "boolean") {
      out.push([k, String(val)]);
    }
  }
  return out;
}
/** Parse a JSON object textarea; returns [value, error]. */
function parseJsonObject(text: string): [Record<string, unknown> | null, string | null] {
  const t = text.trim();
  if (!t) return [{}, null];
  try {
    const v: unknown = JSON.parse(t);
    if (typeof v !== "object" || v === null || Array.isArray(v)) {
      return [null, "Input must be a JSON object."];
    }
    return [v as Record<string, unknown>, null];
  } catch {
    return [null, "Input is not valid JSON."];
  }
}

export function AgentsPage() {
  const [tab, setTab] = useState<TabId>("agents");

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">AI Agents</h1>
        <p className="page-description">
          Registered agents, deterministic coordination, orchestration
          workflows, and the message bus.
        </p>
      </header>

      <Tabs
        items={TABS}
        value={tab}
        onChange={(id) => setTab(id as TabId)}
        label="Agent sections"
        idPrefix="agents"
      />

      <div role="tabpanel" id={`agents-panel-${tab}`} aria-labelledby={`agents-tab-${tab}`} tabIndex={0}>
        {tab === "agents" && <AgentsTab />}
        {tab === "coordinator" && <CoordinatorTab />}
        {tab === "workflows" && <WorkflowsTab />}
        {tab === "messages" && <MessagesTab />}
      </div>
    </div>
  );
}

/* ─── agents tab ───────────────────────────────────────────────────── */

function AgentsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [capability, setCapability] = useState("");
  const [textQuery, setTextQuery] = useState("");
  const [tag, setTag] = useState("");
  const [page, setPage] = useState(0);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  // Execute form
  const [execAgent, setExecAgent] = useState("");
  const [execCapability, setExecCapability] = useState("");
  const [execInput, setExecInput] = useState('{"text": ""}');
  const [execRetries, setExecRetries] = useState("");
  const [execTimeout, setExecTimeout] = useState("");
  const [execResult, setExecResult] = useState<AgentResult | null>(null);

  // Register form
  const [regName, setRegName] = useState("");
  const [regDesc, setRegDesc] = useState("");
  const [regCapKind, setRegCapKind] = useState<CapabilityKind>("retrieval");
  const [regCapName, setRegCapName] = useState("");

  const listQuery = useMemo(
    () => ({
      capability: capability || undefined,
      text_query: textQuery.trim() || undefined,
      tag: tag.trim() || undefined,
      page: page + 1,
      page_size: AGENT_PAGE_SIZE,
    }),
    [capability, textQuery, tag, page]
  );
  const registry = useQuery({
    queryKey: agentsKeys.list(listQuery),
    queryFn: () => getAgents(listQuery),
  });
  const detail = useQuery({
    queryKey: agentsKeys.agent(selectedName ?? "none"),
    queryFn: () => getAgent(selectedName as string),
    enabled: !!selectedName,
  });
  const health = useQuery({
    queryKey: agentsKeys.agentHealth(selectedName ?? "none"),
    queryFn: () => getAgentHealth(selectedName as string),
    enabled: !!selectedName,
  });

  const execute = useMutation({
    mutationFn: executeAgent,
    onSuccess: (r) => {
      setExecResult(r);
      toast.push({
        title: r.status === "succeeded" ? "Agent execution complete" : `Agent execution ${r.status}`,
        description: `${r.agent_name} · ${formatDurationMs(r.duration_ms)}`,
        tone: r.status === "succeeded" ? "success" : "warning",
      });
    },
  });
  const register = useMutation({
    mutationFn: registerAgent,
    onSuccess: (a) => {
      void qc.invalidateQueries({ queryKey: [...agentsKeys.all, "list"] });
      setRegName("");
      setRegDesc("");
      setRegCapName("");
      setSelectedName(a.name);
      toast.push({ title: "Agent registered", description: a.name, tone: "success" });
    },
  });
  const unregister = useMutation({
    mutationFn: unregisterAgent,
    onSuccess: (_, name) => {
      void qc.invalidateQueries({ queryKey: [...agentsKeys.all, "list"] });
      setConfirmRemove(null);
      if (selectedName === name) setSelectedName(null);
      toast.push({ title: "Agent removed", description: name, tone: "success" });
    },
  });

  const agents = registry.data?.items ?? [];
  const shortPage = agents.length < AGENT_PAGE_SIZE;
  const execAgentMeta = agents.find((a) => a.name === execAgent) ?? null;
  const execCaps = arr<AgentCapability>(execAgentMeta?.capabilities);
  // Capability comes from the selected agent's declared set — never a default guess.
  const effCapability = execCaps.some((c) => c.kind === execCapability) ? execCapability : "";
  const [parsedInput, inputError] = parseJsonObject(execInput);

  const handleExecute = () => {
    if (execute.isPending || !execAgent || !effCapability || inputError || !parsedInput) return;
    setExecResult(null);
    execute.mutate({
      agent_name: execAgent,
      capability: effCapability as CapabilityKind,
      input: parsedInput,
      max_retries: execRetries.trim() === "" ? undefined : Math.max(0, Number(execRetries) || 0),
      timeout_ms: execTimeout.trim() === "" ? undefined : Math.max(100, Number(execTimeout) || 30000),
    });
  };

  const handleRegister = () => {
    if (register.isPending || regName.trim().length < 1) return;
    register.mutate({
      name: regName.trim(),
      description: regDesc.trim(),
      capabilities: regCapName.trim()
        ? [{ kind: regCapKind, name: regCapName.trim() }]
        : [],
    });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card padding="none">
          <CardHeader
            title="Agent registry"
            description="Agents registered in the backend framework"
            actions={
              <Select aria-label="Filter by capability" value={capability} onChange={(e) => { setCapability(e.target.value); setPage(0); }} className="text-xs">
                <option value="">All capabilities</option>
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            }
          />
          <div className="card-body" aria-live="polite">
            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Input aria-label="Search agents" value={textQuery} onChange={(e) => { setTextQuery(e.target.value); setPage(0); }} placeholder="Search name or description…" className="text-xs" />
              <Input aria-label="Filter by tag" value={tag} onChange={(e) => { setTag(e.target.value); setPage(0); }} placeholder="Tag…" className="text-xs" />
            </div>
            {registry.isPending ? (
              <Skeleton lines={4} />
            ) : registry.isError ? (
              <ErrorState title="Agent registry unavailable" error={registry.error} onRetry={() => void registry.refetch()} />
            ) : agents.length === 0 ? (
              <EmptyState title="No agents registered" description="No agents match these filters, or the backend has registered none yet." />
            ) : (
              <>
                <ul className="space-y-2">
                  {agents.map((a) => (
                    <li key={a.agent_id}>
                      <button
                        type="button"
                        onClick={() => setSelectedName(a.name)}
                        aria-pressed={selectedName === a.name}
                        className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.name}</span>
                          <Badge tone={statusTone(a.status)} size="sm">{a.status || "unknown"}</Badge>
                          <span className="meta-text ml-auto">v{a.version}</span>
                        </div>
                        <p className="meta-text mt-1">
                          {arr<AgentCapability>(a.capabilities).map((c) => c.kind).join(" · ") || str(a.description) || "no capabilities declared"}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <span className="meta-text">Page {page + 1} · {agents.length} shown</span>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</Button>
                    <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>Next</Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card padding="md">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Execute agent</h2>
            <p className="meta-text mb-3 mt-0.5">
              Blocking call: the request stays open until the agent returns.
              Capability must come from the agent's declared set.
            </p>
            <div className="space-y-3">
              <Field label="Agent" id="exec-agent">
                <Select
                  id="exec-agent"
                  value={execAgent}
                  onChange={(e) => {
                    setExecAgent(e.target.value);
                    setExecCapability("");
                    setExecResult(null);
                  }}
                >
                  <option value="">Select agent…</option>
                  {agents.map((a) => (
                    <option key={a.agent_id} value={a.name}>{a.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Capability" id="exec-capability" hint={execAgentMeta ? "Declared by the selected agent" : "Select an agent first"}>
                <Select
                  id="exec-capability"
                  value={effCapability}
                  onChange={(e) => setExecCapability(e.target.value)}
                  disabled={!execAgentMeta}
                >
                  <option value="">Select capability…</option>
                  {execCaps.map((c) => (
                    <option key={c.capability_id} value={c.kind}>{c.kind}{c.name ? ` — ${c.name}` : ""}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Input (JSON object)" id="exec-input" error={inputError}>
                <TextArea id="exec-input" value={execInput} onChange={(e) => setExecInput(e.target.value)} rows={3} className="font-mono text-xs" />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Max retries (optional)" id="exec-retries">
                  <Input id="exec-retries" type="number" min={0} max={10} value={execRetries} onChange={(e) => setExecRetries(e.target.value)} placeholder="agent default" />
                </Field>
                <Field label="Timeout ms (optional)" id="exec-timeout">
                  <Input id="exec-timeout" type="number" min={100} max={600000} value={execTimeout} onChange={(e) => setExecTimeout(e.target.value)} placeholder="30000" />
                </Field>
              </div>
              <Button
                variant="primary"
                loading={execute.isPending}
                disabled={execute.isPending || !execAgent || !effCapability || !!inputError || !parsedInput}
                onClick={handleExecute}
              >
                Execute agent
              </Button>
              {execute.isPending && (
                <div className="rounded-xl border border-brand-200 bg-brand-50/60 p-3 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
                  <p className="text-xs font-medium text-brand-900 dark:text-brand-100">Executing… the request stays open until the agent returns.</p>
                </div>
              )}
              {execute.isError && (
                <ErrorState title="Execution request failed" error={execute.error} onRetry={handleExecute} />
              )}
              {execResult && <AgentResultView result={execResult} />}
            </div>
          </Card>

          <Card padding="md">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Register agent</h2>
            <p className="meta-text mb-3 mt-0.5">
              HTTP registration creates a metadata/echo agent for exercising
              the framework; real executable agents register service-side.
            </p>
            <div className="space-y-3">
              <Field label="Name" id="reg-name">
                <Input id="reg-name" value={regName} onChange={(e) => setRegName(e.target.value)} placeholder="my-agent" />
              </Field>
              <Field label="Description (optional)" id="reg-desc">
                <Input id="reg-desc" value={regDesc} onChange={(e) => setRegDesc(e.target.value)} />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Capability kind" id="reg-cap-kind">
                  <Select id="reg-cap-kind" value={regCapKind} onChange={(e) => setRegCapKind(e.target.value as CapabilityKind)}>
                    {CAPABILITIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Capability name (optional)" id="reg-cap-name">
                  <Input id="reg-cap-name" value={regCapName} onChange={(e) => setRegCapName(e.target.value)} placeholder="retrieve" />
                </Field>
              </div>
              <Button variant="secondary" loading={register.isPending} disabled={register.isPending || regName.trim().length < 1} onClick={handleRegister}>
                Register agent
              </Button>
              {register.isError && (
                <ErrorState title="Registration failed" error={register.error} onRetry={handleRegister} />
              )}
            </div>
          </Card>
        </div>
      </div>

      {selectedName && (
        <AgentDetail
          name={selectedName}
          detail={detail}
          health={health}
          onClose={() => setSelectedName(null)}
          onRemove={(name) => {
            if (confirmRemove === name) {
              unregister.mutate(name);
            } else {
              setConfirmRemove(name);
            }
          }}
          confirmRemove={confirmRemove === selectedName}
          unregister={unregister}
        />
      )}
    </div>
  );
}

function AgentDetail({
  name,
  detail,
  health,
  onClose,
  onRemove,
  confirmRemove,
  unregister,
}: {
  name: string;
  detail: UseQueryResult<AgentMetadata, Error>;
  health: UseQueryResult<AgentHealthCheck, Error>;
  onClose: () => void;
  onRemove: (name: string) => void;
  confirmRemove: boolean;
  unregister: { isPending: boolean; isError: boolean; error: unknown };
}) {
  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">{name}</h2>
          {detail.data && <Badge tone={statusTone(detail.data.status)} size="sm">{detail.data.status || "unknown"}</Badge>}
          <div className="ml-auto flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              loading={unregister.isPending}
              disabled={unregister.isPending}
              onClick={() => onRemove(name)}
            >
              {confirmRemove ? "Confirm removal" : "Remove"}
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
          </div>
        </div>
        {confirmRemove && (
          <p className="meta-text mt-1">Removal unregisters the agent immediately. Press Confirm removal again to proceed.</p>
        )}
        {detail.isPending ? (
          <div className="mt-3"><Skeleton lines={4} /></div>
        ) : detail.isError ? (
          <div className="mt-3">
            <ErrorState title="Agent unavailable" error={detail.error} onRetry={() => void detail.refetch()} />
          </div>
        ) : (
          <AgentDetailBody agent={detail.data} health={health} />
        )}
        {unregister.isError && (
          <div className="mt-2">
            <ErrorState title="Removal failed" error={unregister.error} />
          </div>
        )}
      </div>
    </Card>
  );
}

function AgentDetailBody({
  agent,
  health,
}: {
  agent: AgentMetadata;
  health: UseQueryResult<AgentHealthCheck, Error>;
}) {
  return (
    <div className="mt-3">
      {str(agent.description) && <p className="text-sm text-slate-700 dark:text-slate-200">{agent.description}</p>}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
        <div>
          <dt className="meta-text">Version</dt>
          <dd className="text-slate-700 dark:text-slate-200">v{agent.version} · by {agent.author || "unknown"}</dd>
        </div>
        <div>
          <dt className="meta-text">Priority / retries / timeout</dt>
          <dd className="text-slate-700 dark:text-slate-200">
            {agent.priority} · {agent.default_max_retries} · {formatDurationMs(agent.default_timeout_ms)}
          </dd>
        </div>
        <div>
          <dt className="meta-text">Registered</dt>
          <dd className="text-slate-700 dark:text-slate-200">{agent.registered_at ? formatRelative(agent.registered_at) : "time unknown"}</dd>
        </div>
        <div>
          <dt className="meta-text">Tags</dt>
          <dd className="text-slate-700 dark:text-slate-200">{arr(agent.tags).join(", ") || "none"}</dd>
        </div>
      </dl>

      <section aria-label="Capabilities" className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Capabilities ({arr<AgentCapability>(agent.capabilities).length})
        </h3>
        {arr<AgentCapability>(agent.capabilities).length === 0 ? (
          <p className="meta-text mt-1">This agent declares no capabilities.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {arr<AgentCapability>(agent.capabilities).map((c) => (
              <li key={c.capability_id} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-slate-100">{c.name}</span>
                  <Badge size="sm">{c.kind}</Badge>
                </div>
                {str(c.description) && <p className="meta-text mt-1">{c.description}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Health snapshot" className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Health snapshot</h3>
        {health.isPending ? (
          <Skeleton className="mt-2 h-16" />
        ) : health.isError ? (
          <p className="meta-text mt-1">Health snapshot unavailable.</p>
        ) : health.data ? (
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs lg:grid-cols-4">
            <div>
              <dt className="meta-text">State</dt>
              <dd><Badge tone={health.data.healthy ? "success" : "danger"} size="sm">{health.data.healthy ? "Healthy" : "Unhealthy"}</Badge></dd>
            </div>
            <div>
              <dt className="meta-text">Invocations</dt>
              <dd className="text-slate-700 dark:text-slate-200">
                {formatNumber(health.data.total_invocations)} ({formatNumber(health.data.successful_invocations)} ok · {formatNumber(health.data.failed_invocations)} failed)
              </dd>
            </div>
            <div>
              <dt className="meta-text">Failures in a row</dt>
              <dd className="text-slate-700 dark:text-slate-200">{formatNumber(health.data.consecutive_failures)}</dd>
            </div>
            <div>
              <dt className="meta-text">Last error</dt>
              <dd className="truncate text-slate-700 dark:text-slate-200" title={health.data.last_error || undefined}>
                {health.data.last_error || "none recorded"}
              </dd>
            </div>
          </dl>
        ) : null}
      </section>
    </div>
  );
}

function AgentResultView({ result: r }: { result: AgentResult }) {
  const failed = r.status !== "succeeded";
  return (
    <div className={failed ? "rounded-xl border border-red-200 bg-red-50/60 p-3 dark:border-red-900/40 dark:bg-red-950/20" : "rounded-xl border border-slate-200 p-3 dark:border-slate-800"} role="status">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-slate-900 dark:text-slate-100">Result {r.result_id}</span>
        <Badge tone={statusTone(r.status)} size="sm">{r.status}</Badge>
        <span className="meta-text ml-auto">
          {r.agent_name} · attempt {r.attempts} · {formatDurationMs(r.duration_ms)}
        </span>
      </div>
      {failed && str(r.error) && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{r.error}</p>}
      {scalarEntries(r.output).length > 0 ? (
        <dl className="mt-2 space-y-1 text-xs">
          {scalarEntries(r.output).map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="meta-text shrink-0">{k}</dt>
              <dd className="min-w-0 break-words text-slate-700 dark:text-slate-200">{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="meta-text mt-1">No plain-text output fields. Output is a structured payload.</p>
      )}
      <p className="meta-text mt-1">Task {r.task_id || "—"} · started {r.started_at ? formatRelative(r.started_at) : "unknown"} · completed {r.completed_at ? formatRelative(r.completed_at) : "unknown"}</p>
    </div>
  );
}

/* ─── coordinator tab ──────────────────────────────────────────────── */

const DEFAULT_MAX_STEPS = 8;

function CoordinatorTab() {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [caps, setCaps] = useState<CapabilityKind[]>([]);
  const [maxSteps, setMaxSteps] = useState(DEFAULT_MAX_STEPS);
  const [result, setResult] = useState<CoordinatorResult | null>(null);

  const run = useMutation({
    mutationFn: coordinate,
    onSuccess: (r) => {
      setResult(r);
      toast.push({
        title: r.status === "succeeded" ? "Coordination complete" : `Coordination ${r.status}`,
        description: `${r.step_results?.length ?? 0} step(s) · ${formatDurationMs(r.duration_ms)}`,
        tone: r.status === "succeeded" ? "success" : "warning",
      });
    },
  });

  const toggleCap = (c: CapabilityKind) => {
    setCaps((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };

  const handleRun = () => {
    if (run.isPending || query.trim().length < 1) return;
    setResult(null);
    run.mutate({ query: query.trim(), desired_capabilities: caps, max_steps: maxSteps });
  };

  return (
    <div className="space-y-4">
      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Coordinate work</h2>
        <p className="meta-text mb-3 mt-0.5">
          Deterministic routing: the backend maps keywords to capabilities
          with fixed rules — plan, distribute, execute. The call blocks until
          every step returns.
        </p>
        <Field label="Request" id="coord-query" hint="What should the agents do?">
          <TextArea id="coord-query" value={query} onChange={(e) => setQuery(e.target.value)} rows={2} placeholder="e.g. Search KYC documents and summarize the changes" />
        </Field>
        <fieldset className="mt-3">
          <legend className="meta-text mb-1">Desired capabilities (optional — inferred from keywords when empty)</legend>
          <div className="flex flex-wrap gap-1.5">
            {CAPABILITIES.map((c) => {
              const on = caps.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggleCap(c)}
                  aria-pressed={on}
                  className={on
                    ? "rounded-full bg-brand-500 px-2.5 py-1 text-xs font-medium text-white"
                    : "rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:text-slate-300"}
                >
                  {c}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[140px_auto]">
          <Field label="Max steps" id="coord-steps" hint="1–32">
            <Input
              id="coord-steps"
              type="number"
              min={1}
              max={32}
              value={maxSteps}
              onChange={(e) => setMaxSteps(Math.min(32, Math.max(1, Number(e.target.value) || DEFAULT_MAX_STEPS)))}
            />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" loading={run.isPending} disabled={run.isPending || query.trim().length < 1} onClick={handleRun}>
              Run coordinator
            </Button>
          </div>
        </div>
        {run.isPending && (
          <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/60 p-3 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
            <p className="text-xs font-medium text-brand-900 dark:text-brand-100">Coordinating… plans and executes every step before returning.</p>
          </div>
        )}
        {run.isError && (
          <div className="mt-3">
            <ErrorState title="Coordination failed" error={run.error} onRetry={handleRun} />
          </div>
        )}
      </Card>

      {result && <CoordinatorResultView result={result} />}
    </div>
  );
}

function CoordinatorResultView({ result: r }: { result: CoordinatorResult }) {
  const steps = arr<AgentResult>(r.step_results);
  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Coordination result</h3>
          <Badge tone={statusTone(str(r.status) ?? "")} size="sm">{str(r.status) ?? "unknown"}</Badge>
          <span className="meta-text ml-auto">{formatDurationMs(r.duration_ms)}</span>
        </div>
        <p className="meta-text mt-1">
          Plan {str(r.plan_id) ?? "—"} · {steps.length} step(s)
          {arr(r.selected_agents).length > 0 ? ` · agents: ${arr(r.selected_agents).join(", ")}` : ""}
          {num(r.conflicts_resolved) ? ` · ${r.conflicts_resolved} conflict(s) resolved` : ""}
        </p>
        {str(r.notes) && <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">{r.notes}</p>}

        {steps.length === 0 ? (
          <p className="meta-text mt-3">No step results returned.</p>
        ) : (
          <ol className="mt-3 space-y-1.5">
            {steps.map((s, i) => (
              <li key={str(s.result_id) ?? `step-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                <div className="flex flex-wrap items-center gap-2">
                  <span aria-hidden className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">{i + 1}</span>
                  <span className="font-medium text-slate-900 dark:text-slate-100">{str(s.agent_name) ?? "unassigned agent"}</span>
                  <Badge tone={statusTone(str(s.status) ?? "")} size="sm">{str(s.status) ?? "unknown"}</Badge>
                  <span className="meta-text ml-auto">attempt {s.attempts} · {formatDurationMs(s.duration_ms)}</span>
                </div>
                {str(s.status) !== "succeeded" && str(s.error) && (
                  <p className="mt-1 text-red-700 dark:text-red-300">{s.error}</p>
                )}
              </li>
            ))}
          </ol>
        )}

        {scalarEntries(r.final_output).length > 0 && (
          <section aria-label="Final output" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Final output</h4>
            <dl className="mt-1 space-y-1 text-xs">
              {scalarEntries(r.final_output).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="meta-text shrink-0">{k}</dt>
                  <dd className="min-w-0 break-words text-slate-700 dark:text-slate-200">{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>
    </Card>
  );
}

/* ─── workflows tab ────────────────────────────────────────────────── */

interface StepDraft {
  clientId: string;
  agent_name: string;
  capability: string;
  description: string;
  depends_on: string[];
}

let stepCounter = 0;
function newStepDraft(): StepDraft {
  stepCounter += 1;
  return { clientId: `step-${stepCounter}`, agent_name: "", capability: "reasoning", description: "", depends_on: [] };
}

function WorkflowsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState("sequential");
  const [steps, setSteps] = useState<StepDraft[]>(() => {
    // Reset per mount so step IDs (step-1, step-2, …) are deterministic.
    stepCounter = 0;
    return [newStepDraft()];
  });
  const [runQuery, setRunQuery] = useState("");
  const [runResult, setRunResult] = useState<AgentWorkflow | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);

  const workflows = useQuery({ queryKey: agentsKeys.workflows(), queryFn: getWorkflows });

  const create = useMutation({
    mutationFn: createWorkflow,
    onSuccess: (w) => {
      void qc.invalidateQueries({ queryKey: agentsKeys.workflows() });
      setName("");
      setDescription("");
      setSteps([newStepDraft()]);
      toast.push({ title: "Workflow created", description: w.name, tone: "success" });
    },
  });
  const run = useMutation({
    mutationFn: ({ id, query }: { id: string; query?: string }) =>
      runWorkflow(id, query ? { query } : {}),
    onSuccess: (r) => {
      setRunResult(r);
      setRunningId(null);
      toast.push({
        title: r.status === "succeeded" ? "Workflow run complete" : `Workflow run ${r.status}`,
        description: `${r.workflow_name} · ${formatDurationMs(r.duration_ms)}`,
        tone: r.status === "succeeded" ? "success" : "warning",
      });
    },
    onError: () => setRunningId(null),
  });

  const updateStep = (clientId: string, patch: Partial<StepDraft>) => {
    setSteps((prev) => prev.map((s) => (s.clientId === clientId ? { ...s, ...patch } : s)));
  };
  const toggleDep = (clientId: string, depId: string) => {
    setSteps((prev) =>
      prev.map((s) =>
        s.clientId === clientId
          ? { ...s, depends_on: s.depends_on.includes(depId) ? s.depends_on.filter((d) => d !== depId) : [...s.depends_on, depId] }
          : s
      )
    );
  };

  const stepErrors: string[] = [];
  steps.forEach((s, i) => {
    if (!s.agent_name.trim()) stepErrors.push(`Step ${i + 1} needs an agent name.`);
  });

  const handleCreate = () => {
    if (create.isPending || name.trim().length < 1 || stepErrors.length > 0) return;
    create.mutate({
      name: name.trim(),
      description: description.trim(),
      graph: {
        mode,
        steps: steps.map((s) => ({
          step_id: s.clientId,
          agent_name: s.agent_name.trim(),
          capability: s.capability,
          description: s.description.trim(),
          depends_on: s.depends_on,
        })),
      },
    });
  };

  const handleRun = (id: string) => {
    if (run.isPending) return;
    setRunResult(null);
    setRunningId(id);
    run.mutate({ id, query: runQuery.trim() || undefined });
  };

  const list = workflows.data ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card padding="none">
          <CardHeader title="Workflows" description="Reusable orchestration definitions, as stored" />
          <div className="card-body" aria-live="polite">
            {workflows.isPending ? (
              <Skeleton lines={4} />
            ) : workflows.isError ? (
              <ErrorState title="Workflows unavailable" error={workflows.error} onRetry={() => void workflows.refetch()} />
            ) : list.length === 0 ? (
              <EmptyState title="No workflows" description="Define one with the builder. The backend stores definitions as given." />
            ) : (
              <ul className="space-y-2">
                {list.map((w) => {
                  const wSteps = arr<WorkflowGraphStep>(w.graph?.steps);
                  return (
                    <li key={w.workflow_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{w.name}</span>
                        <Badge size="sm">{wSteps.length} step(s)</Badge>
                        {str(w.graph?.mode) && <Badge size="sm">{w.graph.mode}</Badge>}
                        <span className="meta-text ml-auto">{w.created_at ? formatRelative(w.created_at) : "time unknown"}</span>
                      </div>
                      {str(w.description) && <p className="meta-text mt-1">{w.description}</p>}
                      {wSteps.length > 0 && (
                        <ol className="meta-text mt-1 space-y-0.5">
                          {wSteps.map((s, i) => (
                            <li key={str(s.step_id) ?? `s-${i}`}>
                              {i + 1}. {str(s.agent_name) ?? "unnamed agent"} · {str(s.capability) ?? "reasoning"}
                              {str(s.description) ? ` — ${s.description}` : ""}
                            </li>
                          ))}
                        </ol>
                      )}
                      <div className="mt-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={run.isPending && runningId === w.workflow_id}
                          disabled={run.isPending}
                          onClick={() => handleRun(w.workflow_id)}
                        >
                          Run workflow
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card padding="md">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Run query</h2>
            <p className="meta-text mb-2 mt-0.5">Optional input for the next run. Empty falls back to the workflow name/description.</p>
            <Field label="Query" id="wf-run-query">
              <Input id="wf-run-query" value={runQuery} onChange={(e) => setRunQuery(e.target.value)} placeholder="Optional run input…" />
            </Field>
          </Card>

          <Card padding="md">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">New workflow</h2>
            <p className="meta-text mb-3 mt-0.5">
              Steps run in order with declared dependencies. IDs are assigned
              here so dependencies reference real step IDs.
            </p>
            <div className="space-y-3">
              <Field label="Name" id="wf-name">
                <Input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="KYC renewal check" />
              </Field>
              <Field label="Description (optional)" id="wf-desc">
                <Input id="wf-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
              </Field>
              <Field label="Mode" id="wf-mode">
                <Select id="wf-mode" value={mode} onChange={(e) => setMode(e.target.value)}>
                  {EXEC_MODES.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </Select>
              </Field>
              <div className="space-y-2">
                {steps.map((s, i) => (
                  <fieldset key={s.clientId} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                    <legend className="meta-text px-1">Step {i + 1} · id {s.clientId}</legend>
                    <div className="space-y-2">
                      <Field label="Agent name" id={`wf-step-agent-${s.clientId}`}>
                        <Input
                          id={`wf-step-agent-${s.clientId}`}
                          value={s.agent_name}
                          onChange={(e) => updateStep(s.clientId, { agent_name: e.target.value })}
                          placeholder="research-agent"
                        />
                      </Field>
                      <div className="grid grid-cols-2 gap-2">
                        <Field label="Capability" id={`wf-step-cap-${s.clientId}`}>
                          <Select id={`wf-step-cap-${s.clientId}`} value={s.capability} onChange={(e) => updateStep(s.clientId, { capability: e.target.value })}>
                            {CAPABILITIES.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </Select>
                        </Field>
                        <Field label="Description" id={`wf-step-desc-${s.clientId}`}>
                          <Input id={`wf-step-desc-${s.clientId}`} value={s.description} onChange={(e) => updateStep(s.clientId, { description: e.target.value })} />
                        </Field>
                      </div>
                      {i > 0 && (
                        <div>
                          <span className="meta-text mb-1 block">Depends on</span>
                          <div className="flex flex-wrap gap-1.5">
                            {steps.slice(0, i).map((prev) => {
                              const on = s.depends_on.includes(prev.clientId);
                              return (
                                <button
                                  key={prev.clientId}
                                  type="button"
                                  onClick={() => toggleDep(s.clientId, prev.clientId)}
                                  aria-pressed={on}
                                  className={on
                                    ? "rounded-full bg-brand-500 px-2 py-0.5 text-[11px] font-medium text-white"
                                    : "rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600 dark:border-slate-700 dark:text-slate-300"}
                                >
                                  {prev.clientId}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )}
                      {steps.length > 1 && (
                        <Button variant="ghost" size="sm" onClick={() => setSteps((prev) => prev.filter((x) => x.clientId !== s.clientId))}>
                          Remove step
                        </Button>
                      )}
                    </div>
                  </fieldset>
                ))}
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setSteps((prev) => [...prev, newStepDraft()])}>
                  Add step
                </Button>
                <Button variant="primary" size="sm" loading={create.isPending} disabled={create.isPending || name.trim().length < 1 || stepErrors.length > 0} onClick={handleCreate}>
                  Create workflow
                </Button>
              </div>
              {stepErrors.length > 0 && (
                <ul className="text-xs text-red-600 dark:text-red-400">
                  {stepErrors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              {create.isError && (
                <ErrorState title="Workflow creation failed" error={create.error} onRetry={handleCreate} />
              )}
            </div>
          </Card>
        </div>
      </div>

      {run.isPending && (
        <div className="rounded-xl border border-brand-200 bg-brand-50/60 p-4 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
          <p className="text-sm font-medium text-brand-900 dark:text-brand-100">Workflow running… the request stays open until orchestration finishes.</p>
        </div>
      )}
      {run.isError && (
        <ErrorState title="Workflow run request failed" error={run.error} />
      )}
      {runResult && <WorkflowRunView run={runResult} />}
    </div>
  );
}

function WorkflowRunView({ run: r }: { run: AgentWorkflow }) {
  const failed = r.status !== "succeeded";
  const result = r.result && typeof r.result === "object" ? (r.result as Record<string, unknown>) : null;
  const contributions = arr<{ agent_name?: unknown; status?: unknown; summary?: unknown }>(result?.contributions);
  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Run {r.run_id}</h3>
          <Badge tone={statusTone(r.status)} size="sm">{r.status}</Badge>
          <span className="meta-text ml-auto">
            {str(r.workflow_name) ?? r.workflow_id} · {formatDurationMs(r.duration_ms)}
          </span>
        </div>
        {failed && str(r.error) && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{r.error}</p>}
        <p className="meta-text mt-1">
          Started {r.started_at ? formatRelative(r.started_at) : "unknown"} · completed {r.completed_at ? formatRelative(r.completed_at) : "unknown"}
        </p>
        {contributions.length > 0 && (
          <section aria-label="Agent contributions" className="mt-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Agent contributions ({contributions.length})
            </h4>
            <ul className="mt-2 space-y-1.5">
              {contributions.map((c, i) => (
                <li key={i} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{str(c.agent_name) ?? "unnamed agent"}</span>
                    <Badge tone={statusTone(str(c.status) ?? "")} size="sm">{str(c.status) ?? "unknown"}</Badge>
                  </div>
                  {str(c.summary) && <p className="mt-1 text-slate-600 dark:text-slate-300">{str(c.summary)}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
        {result && scalarEntries(result).filter(([k]) => !["contributions"].includes(k)).length > 0 && (
          <dl className="mt-3 space-y-1 text-xs">
            {scalarEntries(result)
              .filter(([k]) => !["contributions"].includes(k))
              .slice(0, 8)
              .map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="meta-text shrink-0">{k}</dt>
                  <dd className="min-w-0 break-words text-slate-700 dark:text-slate-200">{truncate(v, 200)}</dd>
                </div>
              ))}
          </dl>
        )}
      </div>
    </Card>
  );
}

/* ─── messages tab ─────────────────────────────────────────────────── */

const MESSAGE_LIMIT = 50;

function MessagesTab() {
  const qc = useQueryClient();
  const [fromAgent, setFromAgent] = useState("");
  const [toAgent, setToAgent] = useState("");
  const [limit, setLimit] = useState(MESSAGE_LIMIT);

  const msgQuery = useMemo(
    () => ({
      from_agent: fromAgent.trim() || undefined,
      to_agent: toAgent.trim() || undefined,
      limit,
    }),
    [fromAgent, toAgent, limit]
  );
  const messages = useQuery({
    queryKey: agentsKeys.messages(msgQuery),
    queryFn: () => getAgentMessages(msgQuery),
  });
  const collaborations = useQuery({
    queryKey: agentsKeys.collaborations(),
    queryFn: getCollaborations,
  });

  const msgs = messages.data ?? [];

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Message bus"
          description="Recorded agent-to-agent messages (in-memory history, not a live stream)"
          actions={
            <Button variant="ghost" size="sm" onClick={() => void qc.invalidateQueries({ queryKey: [...agentsKeys.all, "messages"] })}>
              Refresh messages
            </Button>
          }
        />
        <div className="card-body" aria-live="polite">
          <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Field label="From agent" id="msg-from">
              <Input id="msg-from" value={fromAgent} onChange={(e) => setFromAgent(e.target.value)} placeholder="research-agent" className="text-xs" />
            </Field>
            <Field label="To agent" id="msg-to">
              <Input id="msg-to" value={toAgent} onChange={(e) => setToAgent(e.target.value)} placeholder="compliance-agent" className="text-xs" />
            </Field>
            <Field label="Limit" id="msg-limit" hint="Server-kept maximum">
              <Input
                id="msg-limit"
                type="number"
                min={1}
                max={500}
                value={limit}
                onChange={(e) => setLimit(Math.min(500, Math.max(1, Number(e.target.value) || MESSAGE_LIMIT)))}
                className="text-xs"
              />
            </Field>
          </div>
          {messages.isPending ? (
            <Skeleton lines={5} />
          ) : messages.isError ? (
            <ErrorState title="Messages unavailable" error={messages.error} onRetry={() => void messages.refetch()} />
          ) : msgs.length === 0 ? (
            <EmptyState title="No messages" description="The bus has recorded nothing matching these filters yet." />
          ) : (
            <ul className="max-h-[480px] space-y-2 overflow-y-auto">
              {msgs.map((m) => (
                <li key={m.message_id} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900 dark:text-slate-100">{m.from_agent}</span>
                    <span aria-hidden>→</span>
                    <span className="text-slate-600 dark:text-slate-300">{m.to_agent}</span>
                    <Badge size="sm">{m.kind}</Badge>
                    <span className="meta-text ml-auto">{m.created_at ? formatRelative(m.created_at) : "time unknown"}</span>
                  </div>
                  {scalarEntries(m.payload).length > 0 ? (
                    <dl className="meta-text mt-1 space-y-0.5">
                      {scalarEntries(m.payload).slice(0, 4).map(([k, v]) => (
                        <div key={k} className="flex gap-1.5">
                          <dt className="shrink-0">{k}:</dt>
                          <dd className="min-w-0 truncate" title={v}>{v}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="meta-text mt-1">No plain-text payload fields.</p>
                  )}
                  {(str(m.correlation_id) || str(m.in_reply_to)) && (
                    <p className="meta-text mt-0.5">
                      {[m.correlation_id && `correlation ${m.correlation_id}`, m.in_reply_to && `in reply to ${m.in_reply_to}`]
                        .filter(Boolean).join(" · ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Collaborations" description="Recorded agent-to-agent calls within runs" />
        <div className="card-body" aria-live="polite">
          {collaborations.isPending ? (
            <Skeleton lines={3} />
          ) : collaborations.isError ? (
            <ErrorState title="Collaborations unavailable" error={collaborations.error} onRetry={() => void collaborations.refetch()} />
          ) : (collaborations.data ?? []).length === 0 ? (
            <EmptyState title="No collaborations" description="No agent-to-agent calls have been recorded." />
          ) : (
            <ul className="space-y-2">
              {(collaborations.data ?? []).map((c) => (
                <li key={c.collaboration_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge size="sm">{c.from_agent} → {c.to_agent}</Badge>
                    <Badge size="sm">{c.request_kind}</Badge>
                    <span className="meta-text ml-auto">{c.created_at ? formatRelative(c.created_at) : "time unknown"}</span>
                  </div>
                  <p className="meta-text mt-1">
                    {arr(c.evidence_keys).length} evidence key(s) · {arr(c.result_keys).length} result key(s) · {arr(c.shared_context_keys).length} shared context key(s) · {formatDurationMs(c.duration_ms)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
