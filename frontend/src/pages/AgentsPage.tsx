import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, Select, TextArea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAgents, executeAgent, getCollaborations, getAgentMessages, getWorkflows, createWorkflow, runWorkflow } from "@/services/api/agentApi";
import { getAnalyticsHealth } from "@/services/api/analyticsApi";
import { useToast } from "@/providers/ToastProvider";
import { formatDurationMs, formatPercent, formatRelative, healthTone } from "@/lib/format";

export function AgentsPage() {
  const [tab, setTab] = useState<"overview" | "health" | "workflows" | "collaboration">("overview");

  const tabs = [
    { id: "overview" as const, label: "Overview" },
    { id: "health" as const, label: "Health" },
    { id: "workflows" as const, label: "Workflows" },
    { id: "collaboration" as const, label: "Collaboration" },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">AI Agents</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Multi-agent orchestration, health monitoring, and execution management.</p>
      </header>

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-xs font-medium transition border-b-2 -mb-px ${
              tab === t.id
                ? "border-brand-500 text-brand-700 dark:text-brand-300"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab />}
      {tab === "health" && <HealthTab />}
      {tab === "workflows" && <WorkflowsTab />}
      {tab === "collaboration" && <CollaborationTab />}
    </div>
  );
}

function OverviewTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: agents, isLoading: aLoading, isError: aError, refetch: aRefetch } = useQuery({
    queryKey: ["agents", "list"], queryFn: getAgents, refetchInterval: 30_000,
  });
  const execute = useMutation({
    mutationFn: executeAgent,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
  const [selectedAgent, setSelectedAgent] = useState<string | undefined>();
  const [input, setInput] = useState("Run a KYC renewal check for the trading desk.");
  const [output, setOutput] = useState<string | null>(null);

  async function handleExecute() {
    if (!selectedAgent) { toast.push({ title: "Pick an agent first", tone: "warning" }); return; }
    try {
      const agent = (agents?.items ?? []).find((a) => a.name === selectedAgent);
      const capability = agent?.capabilities?.[0]?.kind ?? "retrieval";
      const r = await execute.mutateAsync({ agent_name: selectedAgent, capability, input: { text: input } });
      setOutput(JSON.stringify(r, null, 2));
      toast.push({ title: "Agent execution complete", description: `${r.agent_name} · ${r.status}`, tone: r.status === "succeeded" ? "success" : "warning" });
    } catch (err) {
      toast.push({ title: "Execution failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  return (
    <div className="space-y-4">
      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Execute Agent</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[200px_1fr_auto]">
          <Field label="Agent" id="agent-select">
            <Select id="agent-select" value={selectedAgent ?? ""} onChange={(e) => setSelectedAgent(e.target.value)}>
              <option value="">Select agent…</option>
              {(agents?.items ?? []).map((a) => (<option key={a.agent_id} value={a.name}>{a.name}</option>))}
            </Select>
          </Field>
          <Field label="Input" id="agent-input">
            <TextArea id="agent-input" value={input} onChange={(e) => setInput(e.target.value)} rows={1} />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={handleExecute} loading={execute.isPending} disabled={!selectedAgent || !input.trim()}>Run</Button>
          </div>
        </div>
        {output ? (
          <pre className="mt-3 rounded-lg bg-slate-50 p-3 text-[11px] dark:bg-slate-800/40">{output}</pre>
        ) : null}
      </Card>

      <Card padding="none">
        <CardHeader title="Registered Agents" />
        <div className="card-body">
          {aLoading ? <Skeleton lines={4} />
          : aError ? <ErrorState onRetry={aRefetch} />
          : !agents?.items?.length ? <EmptyState title="No agents registered" description="Agents will appear here once the backend registers them." />
          : <ul className="space-y-2">
              {(agents?.items ?? []).map((a) => (
                <li key={a.agent_id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.name}</p>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">{a.capabilities?.map((c) => c.kind).join(", ") || a.description || "—"}</p>
                  </div>
                  <Badge tone="neutral" size="sm">{a.status || "idle"}</Badge>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}

function HealthTab() {
  const { data: health, isLoading: hLoading, isError: hError, refetch: hRefetch } = useQuery({
    queryKey: ["agents", "health"], queryFn: getAnalyticsHealth, refetchInterval: 15_000,
  });

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Total" value={health?.total_agents ?? "—"} />
        <Metric label="Healthy" value={health?.healthy_agents ?? "—"} hint="No failures in window" />
        <Metric label="Degraded" value={health?.degraded_agents ?? "—"} hint="Some failures" />
        <Metric label="Unhealthy" value={health?.unhealthy_agents ?? "—"} hint="Majority of runs failed" />
      </section>

      <Card padding="none">
        <CardHeader title="Per-agent health" description="Health, latency, and confidence" />
        <div className="card-body">
          {hLoading ? <Skeleton lines={5} />
          : hError ? <ErrorState onRetry={hRefetch} />
          : !health?.agents?.length ? <EmptyState title="No agent health data" />
          : <ul className="space-y-2">
              {health.agents.map((a) => {
                return (
                  <li key={a.agent_name} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex items-center gap-2">
                      <Badge tone={healthTone(a.health)} dot>{a.health}</Badge>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.agent_name}</span>
                      <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">{a.total_invocations} runs · {formatPercent(a.success_rate)} success</span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <span><span className="text-slate-500">Success:</span> {formatPercent(a.success_rate)}</span>
                      <span><span className="text-slate-500">Latency:</span> {formatDurationMs(a.average_duration_ms)}</span>
                      <span><span className="text-slate-500">Confidence:</span> {formatPercent(a.average_confidence)}</span>
                    </div>
                    <ProgressBar value={a.success_rate * 100} max={100} tone={a.success_rate > 0.9 ? "success" : a.success_rate > 0.7 ? "warning" : "danger"} className="mt-2" />
                  </li>
                );
              })}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}

function WorkflowsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: workflows, isLoading, isError, refetch } = useQuery({
    queryKey: ["agents", "workflows"], queryFn: getWorkflows,
  });
  const create = useMutation({ mutationFn: createWorkflow, onSuccess: () => qc.invalidateQueries({ queryKey: ["agents", "workflows"] }) });
  const runWf = useMutation({ mutationFn: runWorkflow });
  const [name, setName] = useState("KYC Renewal Check");
  const [description, setDescription] = useState("Validate KYC renewal across portfolio");
  const [definition, setDefinition] = useState(
    JSON.stringify({ steps: [{ step_id: "s1", agent_name: "research-agent", capability: "regulatory_search", depends_on: [] }] }, null, 2)
  );

  async function handleCreate() {
    try { const parsed = JSON.parse(definition); await create.mutateAsync({ name, description, steps: parsed.steps }); toast.push({ title: "Workflow created", tone: "success" }); }
    catch (err) { toast.push({ title: "Invalid definition", description: err instanceof Error ? err.message : "JSON parse error", tone: "danger" }); }
  }

  async function handleRun(id: string) {
    try { const r = await runWf.mutateAsync(id); toast.push({ title: "Workflow started", description: `Execution ${r.execution_id}`, tone: "success" }); }
    catch (err) { toast.push({ title: "Run failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" }); }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padding="none">
        <CardHeader title="Workflows" />
        <div className="card-body">
          {isLoading ? <Skeleton lines={5} />
          : isError ? <ErrorState onRetry={refetch} />
          : !workflows?.length ? <EmptyState title="No workflows yet" description="Create one using the form." />
          : <ul className="space-y-2">
              {workflows.map((w) => (
                <li key={w.workflow_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{w.name}</span>
                    <Badge tone="neutral" size="sm">{w.steps?.length ?? 0} steps</Badge>
                    <div className="ml-auto flex gap-2">
                      <Button size="sm" variant="secondary" onClick={() => handleRun(w.workflow_id)} loading={runWf.isPending}>Run</Button>
                    </div>
                  </div>
                  {w.description ? <p className="mt-1 text-xs text-slate-500">{w.description}</p> : null}
                  <p className="mt-1 text-[10px] text-slate-400">{formatRelative(w.created_at)}</p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">New Workflow</h3>
        <div className="mt-3 space-y-3">
          <Field label="Name" id="wf-name"><TextArea id="wf-name" value={name} onChange={(e) => setName(e.target.value)} rows={1} /></Field>
          <Field label="Description" id="wf-desc"><TextArea id="wf-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={1} /></Field>
          <Field label="Definition (JSON)" id="wf-def"><TextArea id="wf-def" value={definition} onChange={(e) => setDefinition(e.target.value)} rows={6} className="font-mono text-[11px]" /></Field>
          <Button variant="primary" onClick={handleCreate} loading={create.isPending} disabled={!name || !definition}>Create</Button>
        </div>
      </Card>
    </div>
  );
}

function CollaborationTab() {
  const { data: collabs, isLoading: cLoading, isError: cError, refetch: cRefetch } = useQuery({
    queryKey: ["agents", "collaborations"], queryFn: getCollaborations,
  });
  const { data: messages, isLoading: mLoading, isError: mError, refetch: mRefetch } = useQuery({
    queryKey: ["agents", "messages"], queryFn: getAgentMessages, refetchInterval: 5_000,
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padding="none">
        <CardHeader title="Collaborations" />
        <div className="card-body">
          {cLoading ? <Skeleton lines={5} />
          : cError ? <ErrorState onRetry={cRefetch} />
          : !collabs?.length ? <EmptyState title="No collaborations yet" />
          : <ul className="space-y-3">
              {collabs.map((c) => (
                <li key={c.collaboration_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <Badge tone="brand" size="sm">{(c.participants?.length ?? 0)} agents</Badge>
                    <Badge tone="success" size="sm">Consensus {formatPercent(c.consensus)}</Badge>
                    <span className="ml-auto text-[10px] text-slate-500">{formatRelative(c.created_at)}</span>
                  </div>
                  <p className="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">{c.topic}</p>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{c.result_summary}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(c.participants ?? []).map((p) => (<Badge key={p} tone="neutral" size="sm">{p}</Badge>))}
                  </div>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
      <Card padding="none">
        <CardHeader title="Live message bus" description="Agent-to-agent messages"
          actions={<Badge tone="info" dot>Live</Badge>}
        />
        <div className="card-body max-h-[70vh] overflow-y-auto">
          {mLoading ? <Skeleton lines={6} />
          : mError ? <ErrorState onRetry={mRefetch} />
          : !messages?.length ? <EmptyState title="No traffic yet" />
          : <ul className="space-y-2">
              {messages.slice(0, 30).map((m) => (
                <li key={m.message_id} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 dark:text-slate-100">{m.from_agent}</span>
                    <span aria-hidden>→</span>
                    <span className="text-slate-600 dark:text-slate-300">{m.to_agent ?? m.channel}</span>
                    <span className="ml-auto text-[10px] text-slate-400">{formatRelative(m.created_at)}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-slate-500">{typeof m.payload === "object" ? JSON.stringify(m.payload).slice(0, 100) : String(m.payload ?? "")}</p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}
