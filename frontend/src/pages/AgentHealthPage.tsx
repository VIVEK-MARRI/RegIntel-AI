import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useAnalyticsHealth, usePerformance } from "@/hooks/api";
import { formatDurationMs, formatPercent, healthTone } from "@/lib/format";

export function AgentHealthPage() {
  const health = useAnalyticsHealth();
  const performance = usePerformance();

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Agent Health Dashboard
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Real-time health classification across the agent ecosystem.
          </p>
        </div>
        <Badge tone={healthTone(health.data?.overall_health ?? "unknown")} dot>
          {health.data?.overall_health ?? "unknown"}
        </Badge>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Total"
          value={health.data?.total_agents ?? "—"}
        />
        <Metric
          label="Healthy"
          value={health.data?.healthy_agents ?? "—"}
          hint="No failures in window"
        />
        <Metric
          label="Degraded"
          value={health.data?.degraded_agents ?? "—"}
          hint="Some failures"
        />
        <Metric
          label="Unhealthy"
          value={health.data?.unhealthy_agents ?? "—"}
          hint="Majority of runs failed"
        />
      </section>

      <Card padding="none">
        <CardHeader
          title="Per-agent health"
          description="Detailed health, latency, and confidence"
        />
        <div className="card-body">
          {health.isLoading ? (
            <Skeleton lines={5} />
          ) : health.isError ? (
            <ErrorState error={health.error} onRetry={() => health.refetch()} />
          ) : !health.data?.agents || health.data.agents.length === 0 ? (
            <EmptyState
              title="No agent health data"
              description="Run an agent to populate health records."
            />
          ) : (
            <ul className="space-y-2">
              {health.data.agents.map((a) => {
                const perf = (performance.data ?? []).find(
                  (p) => p.agent_name === a.agent_name
                );
                return (
                  <li
                    key={a.agent_name}
                    className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                  >
                    <div className="flex items-center gap-2">
                      <Badge tone={healthTone(a.health)} dot>
                        {a.health}
                      </Badge>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {a.agent_name}
                      </span>
                      <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                        {a.total_invocations} runs · {formatPercent(a.success_rate)} success
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <Stat
                        label="Success rate"
                        value={formatPercent(a.success_rate)}
                      />
                      <Stat
                        label="Avg latency"
                        value={formatDurationMs(a.average_duration_ms)}
                      />
                      <Stat
                        label="Confidence"
                        value={formatPercent(a.average_confidence)}
                      />
                    </div>
                    <ProgressBar
                      value={a.success_rate * 100}
                      max={100}
                      tone={
                        a.health === "unhealthy"
                          ? "danger"
                          : a.health === "degraded"
                            ? "warning"
                            : "success"
                      }
                      className="mt-2"
                    />
                    {perf ? (
                      <div className="mt-2 grid grid-cols-4 gap-2 text-[10px]">
                        {(["p50_duration_ms", "p90_duration_ms", "p95_duration_ms", "p99_duration_ms"] as const).map(
                          (k) => (
                            <div
                              key={k}
                              className="rounded bg-slate-50 px-1.5 py-1 text-center font-mono dark:bg-slate-800/60"
                            >
                              <p className="text-[9px] uppercase text-slate-500 dark:text-slate-400">
                                {k.replace("_duration_ms", "")}
                              </p>
                              <p>{formatDurationMs(perf[k])}</p>
                            </div>
                          )
                        )}
                      </div>
                    ) : null}
                    {a.last_error ? (
                      <p className="mt-2 text-[11px] text-red-600 dark:text-red-300">
                        Last error: {a.last_error}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Card>
    </div>
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
