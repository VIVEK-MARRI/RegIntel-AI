import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useQuery } from "@tanstack/react-query";
import { getAnalyticsOverview, getPerformance, getIntelligenceMetrics, getAlerts } from "@/services/api/analyticsApi";
import { formatPercent, formatRelative, formatNumber } from "@/lib/format";
import { useHealth } from "@/providers/HealthProvider";

export function AnalyticsPage() {
  const health = useHealth();
  const { data: overview } = useQuery({
    queryKey: ["analytics", "overview"], queryFn: getAnalyticsOverview,
    refetchInterval: 30_000,
  });
  const { data: performance, isLoading: pLoading, isError: pError, refetch: pRefetch } = useQuery({
    queryKey: ["analytics", "performance"], queryFn: getPerformance,
    refetchInterval: 30_000,
  });
  const { data: metrics, isLoading: mLoading, isError: mError, refetch: mRefetch } = useQuery({
    queryKey: ["analytics", "intelligence"], queryFn: getIntelligenceMetrics,
    refetchInterval: 30_000,
  });
  const { data: alerts, isLoading: aLoading, isError: aError, refetch: aRefetch } = useQuery({
    queryKey: ["analytics", "alerts"], queryFn: getAlerts,
    refetchInterval: 30_000,
  });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Analytics</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">System intelligence, retrieval analytics, usage metrics, and health status.</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Metric label="System Health"
          value={<span className={health.isHealthy ? "text-emerald-600" : health.isDegraded ? "text-amber-600" : "text-red-600"}>{health.status?.status ?? "Unknown"}</span>}
          hint={health.isLoading ? "Checking…" : health.isError ? "Unreachable" : `v${health.status?.version ?? "?"}`}
        />
        <Metric label="Total Agents" value={overview?.total_agents ?? "—"} hint={overview ? `${overview.total_invocations.toLocaleString()} invocations` : "Loading…"} />
        <Metric label="Success Rate" value={overview ? formatPercent(overview.success_rate) : "—"} />
        <Metric label="Avg Latency" value={overview ? `${Math.round(overview.average_duration_ms)}ms` : "—"} />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Agent Performance" description="Success rates and latency" />
          <div className="card-body">
            {pLoading ? <Skeleton lines={4} />
            : pError ? <ErrorState onRetry={pRefetch} />
            : !performance?.length ? <EmptyState title="No performance data" />
            : <Table>
                <THead><TR><TH>Agent</TH><TH>Invocations</TH><TH>Success</TH><TH>Avg Latency</TH><TH>Health</TH></TR></THead>
                <TBody>
                  {performance.slice(0, 20).map((p) => (
                    <TR key={p.agent_name}>
                      <TD className="font-medium">{p.agent_name}</TD>
                      <TD>{formatNumber(p.total_invocations)}</TD>
                      <TD><Badge tone={p.success_rate > 0.95 ? "success" : p.success_rate > 0.8 ? "warning" : "danger"} size="sm">{formatPercent(p.success_rate)}</Badge></TD>
                      <TD>{Math.round(p.average_duration_ms)}ms</TD>
                      <TD><Badge tone={p.health === "healthy" ? "success" : p.health === "degraded" ? "warning" : "danger"} size="sm">{p.health}</Badge></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            }
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Alerts" description="Recent monitoring alerts" />
          <div className="card-body">
            {aLoading ? <Skeleton lines={4} />
            : aError ? <ErrorState onRetry={aRefetch} />
            : !alerts?.length ? <EmptyState title="No alerts" description="All clear." />
            : <ul className="space-y-2">
                {alerts.slice(0, 10).map((a) => (
                  <li key={a.alert_id} className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                    <Badge tone={a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : "info"} size="sm">{a.severity}</Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-slate-900 dark:text-slate-100">{a.title}</p>
                      <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{a.source} · {formatRelative(a.detected_at)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>
      </section>

      <Card padding="none">
        <CardHeader title="Intelligence Metrics" description="Aggregate invocation and confidence data" />
        <div className="card-body">
          {mLoading ? <Skeleton lines={3} />
          : mError ? <ErrorState onRetry={mRefetch} />
          : !metrics ? <EmptyState title="No metrics data" />
          : <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
              <Metric label="Total Invocations" value={formatNumber(metrics.total_invocations)} />
              <Metric label="Succeeded" value={formatNumber(metrics.succeeded)} />
              <Metric label="Failed" value={formatNumber(metrics.failed)} />
              <Metric label="Avg Confidence" value={formatPercent(metrics.average_confidence)} />
            </div>
          }
        </div>
      </Card>
    </div>
  );
}
