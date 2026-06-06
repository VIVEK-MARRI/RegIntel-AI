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
import {
  useAgent,
  useAgents,
  useAnalyticsHealth,
  useAnalyticsOverview,
  useCost,
  useExecuteAgent,
  useIntelligenceMetrics,
  useLatency,
  useLeaderboard,
  usePerformance,
} from "@/hooks/api";
import { useToast } from "@/providers/ToastProvider";
import { formatDurationMs, formatNumber, formatPercent, healthTone } from "@/lib/format";
import type { AgentPerformance } from "@/types";

export function AgentControlCenterPage() {
  const overview = useAnalyticsOverview();
  const performance = usePerformance();
  const leaderboard = useLeaderboard(10);
  const cost = useCost();
  const metrics = useIntelligenceMetrics();
  const health = useAnalyticsHealth();
  const agents = useAgents();
  const execute = useExecuteAgent();
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
      toast.push({
        title: "Agent execution complete",
        description: `${r.agent_name} · ${r.status}`,
        tone: r.status === "succeeded" ? "success" : "warning",
      });
    } catch (err) {
      toast.push({
        title: "Execution failed",
        description: err instanceof Error ? err.message : "Unexpected error",
        tone: "danger",
      });
    }
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Agent Control Center
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Real-time visibility into agent health, performance, and execution.
          </p>
        </div>
        <Badge tone={healthTone(health.data?.overall_health ?? "unknown")} dot>
          Ecosystem {health.data?.overall_health ?? "unknown"}
        </Badge>
      </header>

      <section
        aria-label="Ecosystem metrics"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Metric
          label="Total agents"
          value={overview.data?.total_agents ?? metrics.data?.total_invocations ?? "—"}
          hint={metrics.data ? `${formatNumber(metrics.data.collaborations)} collaborations` : ""}
        />
        <Metric
          label="Success rate"
          value={
            overview.data
              ? formatPercent(overview.data.success_rate)
              : metrics.data
                ? formatPercent(
                    metrics.data.succeeded /
                      Math.max(1, metrics.data.succeeded + metrics.data.failed)
                  )
                : "—"
          }
          hint={
            metrics.data
              ? `${metrics.data.succeeded} ok · ${metrics.data.failed} failed`
              : ""
          }
        />
        <Metric
          label="Avg latency"
          value={
            overview.data
              ? formatDurationMs(overview.data.average_duration_ms)
              : metrics.data
                ? formatDurationMs(metrics.data.average_duration_ms)
                : "—"
          }
          hint="Across all agents"
        />
        <Metric
          label="Cost / day"
          value={cost.data ? `${cost.data.total_cost_units.toFixed(2)} ${cost.data.currency}` : "—"}
          hint={cost.data ? `${cost.data.per_agent.length} agents billed` : ""}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card padding="none">
          <CardHeader
            title="Agent fleet"
            description="All registered agents with health and activity"
            actions={
              <Badge tone="info">
                {(performance.data ?? []).length} active
              </Badge>
            }
          />
          <div className="card-body space-y-2">
            {performance.isLoading ? (
              <Skeleton lines={6} />
            ) : performance.isError ? (
              <ErrorState
                error={performance.error}
                onRetry={() => performance.refetch()}
              />
            ) : !performance.data || performance.data.length === 0 ? (
              <EmptyState
                title="No agent metrics yet"
                description="Run an agent to start populating performance data."
              />
            ) : (
              <ul className="space-y-2">
                {performance.data.map((p) => (
                  <AgentRow
                    key={p.agent_name}
                    perf={p}
                    selected={selectedAgent === p.agent_name}
                    onSelect={() => setSelectedAgent(p.agent_name)}
                  />
                ))}
              </ul>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          <Card padding="none">
            <CardHeader title="Leaderboard" description="Composite score" />
            <div className="card-body">
              {leaderboard.isLoading ? (
                <Skeleton lines={4} />
              ) : !leaderboard.data || leaderboard.data.length === 0 ? (
                <EmptyState title="No leaderboard data" />
              ) : (
                <ol className="space-y-1.5">
                  {leaderboard.data.slice(0, 8).map((entry) => (
                    <li
                      key={entry.agent_name}
                      className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800/40"
                    >
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">
                        {entry.rank}
                      </span>
                      <span className="flex-1 truncate font-medium text-slate-900 dark:text-slate-100">
                        {entry.agent_name}
                      </span>
                      <Badge tone="success" size="sm">
                        {formatPercent(entry.success_rate)}
                      </Badge>
                      <span className="w-10 text-right font-mono text-slate-700 dark:text-slate-200">
                        {entry.score.toFixed(0)}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </Card>

          <Card padding="none">
            <CardHeader
              title="Quick execute"
              description="Run an agent with a single prompt"
            />
            <div className="card-body space-y-3">
              <Field label="Agent" id="acc-agent">
                <Select
                  id="acc-agent"
                  value={selectedAgent ?? ""}
                  onChange={(e) => setSelectedAgent(e.target.value || undefined)}
                >
                  <option value="">Select an agent…</option>
                  {(agents.data?.items ?? []).map((a) => (
                    <option key={a.agent_id ?? a.name} value={a.name}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Input" id="acc-input">
                <TextArea
                  id="acc-input"
                  rows={3}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                />
              </Field>
              <Button
                variant="primary"
                onClick={handleExecute}
                loading={execute.isPending}
                disabled={!selectedAgent}
              >
                Execute
              </Button>
              {output ? (
                <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-100">
                  {output}
                </pre>
              ) : null}
            </div>
          </Card>
        </div>
      </section>

      {selectedAgent ? <AgentDetailPanel name={selectedAgent} /> : null}
    </div>
  );
}

function AgentRow({
  perf,
  selected,
  onSelect,
}: {
  perf: AgentPerformance;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`w-full rounded-xl border px-3 py-2.5 text-left text-xs transition ${
          selected
            ? "border-brand-500 bg-brand-50 dark:bg-brand-950/30"
            : "border-slate-200 hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
        }`}
      >
        <div className="flex items-center gap-2">
          <Badge tone={healthTone(perf.health)} size="sm" dot>
            {perf.health}
          </Badge>
          <span className="flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
            {perf.agent_name}
          </span>
          <span className="text-[10px] text-slate-500 dark:text-slate-400">
            {perf.total_invocations} runs
          </span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
          <Stat label="Success" value={formatPercent(perf.success_rate)} />
          <Stat label="Latency" value={formatDurationMs(perf.average_duration_ms)} />
          <Stat label="Confidence" value={formatPercent(perf.average_confidence)} />
        </div>
        <div className="mt-2">
          <ProgressBar
            value={perf.success_rate * 100}
            max={100}
            tone={
              perf.health === "unhealthy"
                ? "danger"
                : perf.health === "degraded"
                  ? "warning"
                  : "success"
            }
          />
        </div>
      </button>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 px-2 py-1 dark:bg-slate-800/60">
      <p className="text-[9px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="font-mono text-[11px] text-slate-900 dark:text-slate-100">
        {value}
      </p>
    </div>
  );
}

function AgentDetailPanel({ name }: { name: string }) {
  const detail = useAgent(name);
  const latency = useLatency(name);
  return (
    <Card padding="none">
      <CardHeader
        title={name}
        description="Agent metadata and latency distribution"
        actions={
          <Badge tone="info">
            {latency.data ? `${latency.data.count} samples` : "—"}
          </Badge>
        }
      />
      <div className="card-body grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Capabilities
          </h4>
          {detail.isLoading ? (
            <Skeleton lines={3} className="mt-2" />
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {(detail.data?.capabilities ?? []).map((c) => (
                <Badge key={c} tone="brand" size="sm">
                  {c}
                </Badge>
              ))}
              {!detail.data?.capabilities?.length ? (
                <li className="text-xs text-slate-500 dark:text-slate-400">
                  No capabilities declared.
                </li>
              ) : null}
            </ul>
          )}
          {detail.data?.description ? (
            <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
              {detail.data.description}
            </p>
          ) : null}
        </section>
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Latency percentiles
          </h4>
          {latency.isLoading ? (
            <Skeleton lines={3} className="mt-2" />
          ) : latency.data ? (
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              {(["p50", "p90", "p95", "p99"] as const).map((k) => (
                <div
                  key={k}
                  className="rounded-lg border border-slate-200 p-2 dark:border-slate-800"
                >
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    {k}
                  </p>
                  <p className="font-mono text-sm">{formatDurationMs(latency.data![k])}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              No latency samples.
            </p>
          )}
        </section>
      </div>
    </Card>
  );
}
