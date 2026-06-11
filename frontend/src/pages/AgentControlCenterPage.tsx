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
import { getAgents, getAgent, executeAgent } from "@/services/api/agentApi";
import { getAnalyticsOverview, getPerformance, getLeaderboard, getCost, getIntelligenceMetrics, getAnalyticsHealth, getLatency } from "@/services/api/analyticsApi";
import { useToast } from "@/providers/ToastProvider";
import { formatDurationMs, formatNumber, formatPercent, healthTone } from "@/lib/format";
import type { AgentPerformance } from "@/types";

export function AgentControlCenterPage() {
  const qc = useQueryClient();
  const { data: overview, isError: oError, refetch: oRefetch } = useQuery({
    queryKey: ["agents", "overview"], queryFn: getAnalyticsOverview, refetchInterval: 15_000,
  });
  const { data: performance, isLoading: pLoading, isError: pError, refetch: pRefetch } = useQuery({
    queryKey: ["agents", "performance"], queryFn: getPerformance, refetchInterval: 15_000,
  });
  const { data: leaderboard, isLoading: lLoading, isError: lError, refetch: lRefetch } = useQuery({
    queryKey: ["agents", "leaderboard"], queryFn: () => getLeaderboard(10), refetchInterval: 15_000,
  });
  const { data: cost, isError: cError, refetch: cRefetch } = useQuery({
    queryKey: ["agents", "cost"], queryFn: getCost, refetchInterval: 30_000,
  });
  const { data: metrics, isError: mError, refetch: mRefetch } = useQuery({
    queryKey: ["agents", "intelligence"], queryFn: getIntelligenceMetrics, refetchInterval: 10_000,
  });
  const { data: health, isError: hError, refetch: hRefetch } = useQuery({
    queryKey: ["agents", "health"], queryFn: getAnalyticsHealth, refetchInterval: 15_000,
  });
  const { data: agents, isError: aError, refetch: aRefetch } = useQuery({
    queryKey: ["agents", "list"], queryFn: getAgents, refetchInterval: 30_000,
  });
  const execute = useMutation({
    mutationFn: executeAgent,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
  const toast = useToast();
  const [selectedAgent, setSelectedAgent] = useState<string | undefined>();
  const [input, setInput] = useState("Run a KYC renewal check for the trading desk.");
  const [output, setOutput] = useState<string | null>(null);

  async function handleExecute() {
    if (!selectedAgent) {
      toast.push({ title: "Pick an agent first", tone: "warning" });
      return;
    }
    try {
      const r = await execute.mutateAsync({ agent_name: selectedAgent, input });
      setOutput(JSON.stringify(r, null, 2));
      toast.push({ title: "Agent execution complete", description: `${r.agent_name} · ${r.status}`, tone: r.status === "succeeded" ? "success" : "warning" });
    } catch (err) {
      toast.push({ title: "Execution failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  const errorAny = oError || pError || lError || cError || mError || hError || aError;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Agent Control Center</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Real-time visibility into agent health, performance, and execution.</p>
        </div>
        <Badge tone={healthTone(health?.overall_health ?? "unknown")} dot>
          Ecosystem {health?.overall_health ?? "unknown"}
        </Badge>
      </header>

      <section aria-label="Ecosystem metrics" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total agents" value={overview?.total_agents ?? metrics?.total_invocations ?? "—"}
          hint={metrics ? `${formatNumber(metrics.collaborations)} collaborations` : ""}
        />
        <Metric label="Success rate" value={overview ? formatPercent(overview.success_rate) : metrics ? formatPercent(metrics.succeeded / Math.max(1, metrics.succeeded + metrics.failed)) : "—"}
          hint={metrics ? `${metrics.succeeded} ok · ${metrics.failed} failed` : ""}
        />
        <Metric label="Avg latency" value={overview ? formatDurationMs(overview.average_duration_ms) : metrics ? formatDurationMs(metrics.average_duration_ms) : "—"} hint="Across all agents" />
        <Metric label="Cost / day" value={cost ? `${cost.cost_units.toFixed(2)} ${cost.currency}` : "—"}
          hint={cost ? `${cost.invocations} invocations across agents` : ""}
        />
      </section>

      {errorAny ? <ErrorState onRetry={() => { oRefetch(); pRefetch(); lRefetch(); cRefetch(); mRefetch(); hRefetch(); aRefetch(); }} /> : null}

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card padding="none">
          <CardHeader title="Agent fleet" description="All registered agents with health and activity"
            actions={<Badge tone="info">{(performance ?? []).length} active</Badge>}
          />
          <div className="card-body space-y-2">
            {pLoading ? <Skeleton lines={6} />
            : pError ? <ErrorState onRetry={pRefetch} />
            : !performance?.length ? <EmptyState title="No agent metrics yet" description="Run an agent to start populating performance data." />
            : <ul className="space-y-2">
                {performance.map((p) => (
                  <AgentRow key={p.agent_name} perf={p} selected={selectedAgent === p.agent_name}
                    onSelect={() => setSelectedAgent(p.agent_name)} />
                ))}
              </ul>
            }
          </div>
        </Card>

        <div className="space-y-4">
          <Card padding="none">
            <CardHeader title="Leaderboard" description="Composite score" />
            <div className="card-body">
              {lLoading ? <Skeleton lines={4} />
              : lError ? <ErrorState onRetry={lRefetch} />
              : !leaderboard?.length ? <EmptyState title="No leaderboard data" />
              : <ol className="space-y-1.5">
                  {leaderboard.slice(0, 8).map((entry) => (
                    <li key={entry.agent_name} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800/40">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">{entry.rank}</span>
                      <span className="flex-1 truncate font-medium text-slate-900 dark:text-slate-100">{entry.agent_name}</span>
                      <Badge tone="success" size="sm">{formatPercent(entry.success_rate)}</Badge>
                      <span className="w-10 text-right font-mono text-slate-700 dark:text-slate-200">{entry.score.toFixed(0)}</span>
                    </li>
                  ))}
                </ol>
              }
            </div>
          </Card>

          <Card padding="none">
            <CardHeader title="Quick execute" description="Run an agent with a single prompt" />
            <div className="card-body space-y-3">
              <Field label="Agent" id="acc-agent">
                <Select id="acc-agent" value={selectedAgent ?? ""} onChange={(e) => setSelectedAgent(e.target.value || undefined)}>
                  <option value="">Select an agent…</option>
                  {(agents?.items ?? []).map((a) => (
                    <option key={a.agent_id ?? a.name} value={a.name}>{a.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Input" id="acc-input">
                <TextArea id="acc-input" rows={3} value={input} onChange={(e) => setInput(e.target.value)} />
              </Field>
              <Button variant="primary" onClick={handleExecute} loading={execute.isPending} disabled={!selectedAgent}>Execute</Button>
              {output ? <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-100">{output}</pre> : null}
            </div>
          </Card>
        </div>
      </section>

      {selectedAgent ? <AgentDetailPanel name={selectedAgent} /> : null}
    </div>
  );
}

function AgentRow({ perf, selected, onSelect }: { perf: AgentPerformance; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button type="button" onClick={onSelect}
        className={`w-full rounded-xl border px-3 py-2.5 text-left text-xs transition ${
          selected
            ? "border-brand-500 bg-brand-50 dark:bg-brand-950/30"
            : "border-slate-200 hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
        }`}
      >
        <div className="flex items-center gap-2">
          <Badge tone={healthTone(perf.health)} size="sm" dot>{perf.health}</Badge>
          <span className="flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{perf.agent_name}</span>
          <span className="text-[10px] text-slate-500 dark:text-slate-400">{perf.total_invocations} runs</span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
          <Stat label="Success" value={formatPercent(perf.success_rate)} />
          <Stat label="Latency" value={formatDurationMs(perf.average_duration_ms)} />
          <Stat label="Confidence" value={formatPercent(perf.average_confidence)} />
        </div>
        <div className="mt-2">
          <ProgressBar value={perf.success_rate * 100} max={100}
            tone={perf.health === "unhealthy" ? "danger" : perf.health === "degraded" ? "warning" : "success"} />
        </div>
      </button>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 px-2 py-1 dark:bg-slate-800/60">
      <p className="text-[9px] uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</p>
      <p className="font-mono text-[11px] text-slate-900 dark:text-slate-100">{value}</p>
    </div>
  );
}

function AgentDetailPanel({ name }: { name: string }) {
  const { data: detail, isLoading: dLoading, isError: dError } = useQuery({
    queryKey: ["agents", "detail", name], queryFn: () => getAgent(name),
  });
  const { data: latency, isLoading: lLoading, isError: lError } = useQuery({
    queryKey: ["agents", "latency", name], queryFn: () => getLatency(name),
  });
  return (
    <Card padding="none">
      <CardHeader title={name} description="Agent metadata and latency distribution"
        actions={<Badge tone="info">{latency ? `${latency.count} samples` : "—"}</Badge>}
      />
      <div className="card-body grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Capabilities</h4>
          {dLoading ? <Skeleton lines={3} className="mt-2" />
          : dError ? <ErrorState />
          : <ul className="mt-2 flex flex-wrap gap-1.5">
              {(detail?.capabilities ?? []).map((c) => (<Badge key={c} tone="brand" size="sm">{c}</Badge>))}
              {!detail?.capabilities?.length ? <li className="text-xs text-slate-500 dark:text-slate-400">No capabilities declared.</li> : null}
            </ul>
          }
          {detail?.description ? <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">{detail.description}</p> : null}
        </section>
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Latency percentiles</h4>
          {lLoading ? <Skeleton lines={3} className="mt-2" />
          : lError ? <ErrorState />
          : latency ? <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              {(["p50", "p90", "p95", "p99"] as const).map((k) => (
                <div key={k} className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">{k}</p>
                  <p className="font-mono text-sm">{formatDurationMs(latency[k])}</p>
                </div>
              ))}
            </div>
          : <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">No latency samples.</p>
          }
        </section>
      </div>
    </Card>
  );
}
