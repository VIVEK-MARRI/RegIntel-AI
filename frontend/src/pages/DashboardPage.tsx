import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  getDashboardAlerts,
  getDashboardCompliance,
  getDashboardImpact,
  getDashboardInsights,
  getDashboardMonitoring,
  getDashboardSystem,
  getDashboardTrends,
} from "@/services/api/dashboardApi";
import { getComplianceAssessments } from "@/services/api/complianceApi";
import { getResearchReports } from "@/services/api/researchApi";
import { complianceKeys, dashboardKeys, researchKeys } from "@/lib/queryKeys";
import { toMillis } from "@/lib/dates";
import { formatNumber, formatRelative, formatDurationMs } from "@/lib/format";
import type { RiskInsight } from "@/types/api/dashboard";

/**
 * Operational entry point: system state, attention items, and recent work —
 * every number traced to its backend field (see docs/DASHBOARD_ARCHITECTURE_STAGE06.md).
 * Widgets fail independently; failures never render as zeros.
 */
export function DashboardPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const compliance = useQuery({
    queryKey: dashboardKeys.compliance(),
    queryFn: getDashboardCompliance,
    staleTime: 60_000,
  });
  const alerts = useQuery({
    queryKey: dashboardKeys.alerts(),
    queryFn: getDashboardAlerts,
    staleTime: 60_000,
  });
  const insights = useQuery({
    queryKey: dashboardKeys.insights(),
    queryFn: getDashboardInsights,
    staleTime: 60_000,
  });
  const impact = useQuery({
    queryKey: dashboardKeys.impact(),
    queryFn: getDashboardImpact,
    staleTime: 60_000,
  });
  const monitoring = useQuery({
    queryKey: dashboardKeys.monitoring(),
    queryFn: getDashboardMonitoring,
    staleTime: 60_000,
  });
  const system = useQuery({
    queryKey: dashboardKeys.system(),
    queryFn: getDashboardSystem,
    staleTime: 60_000,
  });
  const trends = useQuery({
    queryKey: dashboardKeys.trends(),
    queryFn: getDashboardTrends,
    staleTime: 60_000,
  });
  const reports = useQuery({
    queryKey: researchKeys.reports(),
    queryFn: () => getResearchReports(),
    staleTime: 60_000,
  });
  const assessments = useQuery({
    queryKey: complianceKeys.assessments(),
    queryFn: getComplianceAssessments,
    staleTime: 60_000,
  });

  const refreshing =
    compliance.isFetching ||
    alerts.isFetching ||
    insights.isFetching ||
    impact.isFetching ||
    monitoring.isFetching ||
    system.isFetching ||
    trends.isFetching ||
    reports.isFetching ||
    assessments.isFetching;

  function refreshAll() {
    if (refreshing) return;
    void qc.invalidateQueries({ queryKey: dashboardKeys.all });
    void qc.invalidateQueries({ queryKey: researchKeys.reports() });
    void qc.invalidateQueries({ queryKey: complianceKeys.assessments() });
  }

  const pendingAlerts =
    alerts.data != null ? (alerts.data.by_status?.["pending"] ?? 0) : null;
  const criticalAlerts =
    alerts.data != null ? (alerts.data.by_severity?.["critical"] ?? 0) : null;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-description">
            Current operational state of the regulatory intelligence system.
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={refreshAll}
          loading={refreshing}
          disabled={refreshing}
        >
          Refresh
        </Button>
      </header>

      {/* KPI strip: authoritative counters only, never list lengths. */}
      <section aria-label="Key indicators" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi
          label="Documents ingested"
          loading={compliance.isLoading}
          error={compliance.isError}
          value={compliance.data ? formatNumber(compliance.data.documents_ingested) : null}
          hint="Registry counter"
        />
        <Kpi
          label="Knowledge graph"
          loading={compliance.isLoading}
          error={compliance.isError}
          value={compliance.data ? `${formatNumber(compliance.data.knowledge_graph_nodes)} nodes` : null}
          hint={compliance.data ? `${formatNumber(compliance.data.knowledge_graph_edges)} edges` : undefined}
        />
        <Kpi
          label="Research reports"
          loading={compliance.isLoading}
          error={compliance.isError}
          value={compliance.data ? formatNumber(compliance.data.research_reports) : null}
          hint="Generated reports"
        />
        <Kpi
          label="Pending alerts"
          loading={alerts.isLoading}
          error={alerts.isError}
          value={pendingAlerts != null ? formatNumber(pendingAlerts) : null}
          hint={criticalAlerts != null && criticalAlerts > 0 ? `${criticalAlerts} critical` : "None critical"}
        />
      </section>

      {/* Attention: risk + alerts. */}
      <section aria-label="Needs attention" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Risk overview" description="Aggregate risk posture and insights" />
          <div className="card-body">
            {insights.isLoading ? (
              <Skeleton lines={4} />
            ) : insights.isError || !insights.data ? (
              <ErrorState
                title="Risk data unavailable"
                error={insights.error}
                onRetry={() => void insights.refetch()}
              />
            ) : (
              <RiskBody
                level={insights.data.risk_level}
                score={insights.data.risk_score}
                generatedMillis={toMillis(insights.data.generated_at)}
                insights={insights.data.insights ?? []}
              />
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Alerts" description="Alert volume and delivery" />
          <div className="card-body">
            {alerts.isLoading ? (
              <Skeleton lines={4} />
            ) : alerts.isError || !alerts.data ? (
              <ErrorState
                title="Alert data unavailable"
                error={alerts.error}
                onRetry={() => void alerts.refetch()}
              />
            ) : alerts.data.total === 0 ? (
              <EmptyState title="No alerts" description="The alerting service has nothing queued." />
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(alerts.data.by_severity ?? {}).map(([sev, count]) => (
                    <Badge
                      key={sev}
                      tone={sev === "critical" ? "danger" : sev === "high" ? "warning" : "info"}
                      size="sm"
                    >
                      {sev}: {count}
                    </Badge>
                  ))}
                </div>
                <p className="supporting-text">
                  {formatNumber(alerts.data.total)} total ·{" "}
                  {Math.round(alerts.data.delivery_rate * 100)}% delivered
                  {alerts.data.digests_generated > 0
                    ? ` · ${alerts.data.digests_generated} digests`
                    : null}
                </p>
              </div>
            )}
          </div>
        </Card>
      </section>

      {/* System: impact distribution + monitoring + components. */}
      <section aria-label="System" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Impact distribution" description="Impact reports by level" />
          <div className="card-body">
            {impact.isLoading ? (
              <Skeleton lines={3} />
            ) : impact.isError || !impact.data ? (
              <ErrorState
                title="Impact data unavailable"
                error={impact.error}
                onRetry={() => void impact.refetch()}
              />
            ) : impact.data.total === 0 ? (
              <EmptyState title="No impact reports yet" description="Distribution appears once impact analysis runs." />
            ) : (
              <ImpactBar
                counts={impact.data.counts ?? {}}
                total={impact.data.total}
                average={impact.data.average_score}
              />
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Monitoring & services" description="Pipeline and component health" />
          <div className="card-body space-y-3">
            {monitoring.isLoading || system.isLoading ? (
              <Skeleton lines={4} />
            ) : monitoring.isError || system.isError || !monitoring.data || !system.data ? (
              <ErrorState
                title="System data unavailable"
                error={monitoring.error ?? system.error}
                onRetry={() => {
                  void monitoring.refetch();
                  void system.refetch();
                }}
              />
            ) : (
              <>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                      {formatNumber(monitoring.data.sources_monitored)}
                    </p>
                    <p className="meta-text">Sources</p>
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                      {formatNumber(monitoring.data.documents_discovered)}
                    </p>
                    <p className="meta-text">Discovered</p>
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                      {formatNumber(monitoring.data.monitor_failures)}
                    </p>
                    <p className="meta-text">Failures</p>
                  </div>
                </div>
                <ul className="space-y-1.5">
                  {Object.entries(system.data.components ?? {}).map(([name, state]) => (
                    <li key={name} className="flex items-center gap-2 text-xs">
                      <Badge
                        tone={state === "ok" ? "success" : state === "degraded" ? "warning" : "danger"}
                        size="sm"
                      >
                        {state}
                      </Badge>
                      <span className="text-slate-700 dark:text-slate-200">{name}</span>
                    </li>
                  ))}
                </ul>
                <p className="meta-text">
                  {monitoring.data.last_run_at != null
                    ? `Last run ${formatRelative(toMillis(monitoring.data.last_run_at))}`
                    : "No runs recorded"}
                  {` · uptime ${formatDurationMs(system.data.uptime_seconds * 1000)}`}
                </p>
              </>
            )}
          </div>
        </Card>
      </section>

      {/* Pipeline totals from trend series (single honest numbers, not charts). */}
      <section aria-label="Pipeline totals">
        <Card padding="none">
          <CardHeader title="Pipeline totals" description="Cumulative counters from trend series" />
          <div className="card-body">
            {trends.isLoading ? (
              <Skeleton lines={3} />
            ) : trends.isError || !trends.data ? (
              <ErrorState
                title="Trend data unavailable"
                error={trends.error}
                onRetry={() => void trends.refetch()}
              />
            ) : (trends.data.items ?? []).length === 0 ? (
              <EmptyState title="No trend data yet" />
            ) : (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {(trends.data.items ?? []).map((t) => (
                  <li key={t.name} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                    <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                      {formatNumber(latestValue(t.points))}
                      {t.unit ? <span className="ml-1 text-xs font-normal text-slate-500">{t.unit}</span> : null}
                    </p>
                    <p className="meta-text">{t.name}</p>
                    <p className="meta-text">
                      {t.direction === "flat" ? "— steady" : `${t.direction} ${typeof t.delta_pct === "number" ? t.delta_pct.toFixed(1) : "�"}%`}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </section>

      {/* Recent work: informational rows (no detail routes exist yet). */}
      <section aria-label="Recent work" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Research reports" />
          <div className="card-body">
            {reports.isLoading ? (
              <Skeleton lines={4} />
            ) : reports.isError ? (
              <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />
            ) : !reports.data?.length ? (
              <EmptyState title="No reports yet" description="Run research to generate grounded reports." />
            ) : (
              <ul className="space-y-2">
                {reports.data.slice(0, 5).map((r) => (
                  <li key={r.report_id} className="flex items-center gap-2 text-xs">
                    <Badge tone="brand" size="sm">{r.kind}</Badge>
                    <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                      {r.summary || r.query}
                    </span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400">
                      {formatRelative(toMillis(r.generated_at))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Assessments" />
          <div className="card-body">
            {assessments.isLoading ? (
              <Skeleton lines={4} />
            ) : assessments.isError ? (
              <ErrorState error={assessments.error} onRetry={() => void assessments.refetch()} />
            ) : !assessments.data?.length ? (
              <EmptyState title="No assessments yet" description="Run a compliance assessment to populate this list." />
            ) : (
              <ul className="space-y-2">
                {assessments.data.slice(0, 5).map((a) => (
                  <li key={a.assessment_id} className="flex items-center gap-2 text-xs">
                    <Badge
                      tone={a.risk_level === "critical" ? "danger" : a.risk_level === "high" ? "warning" : "info"}
                      size="sm"
                    >
                      {a.risk_level}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                      {a.document_id ?? a.assessment_id}
                    </span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400">
                      {formatRelative(toMillis(a.generated_at))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </section>

      {/* Real destinations only. */}
      <section aria-label="Continue work" className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => navigate("/documents")}>
          Upload Document
        </Button>
        <Button variant="secondary" onClick={() => navigate("/copilot")}>
          Ask Copilot
        </Button>
        <Button variant="ghost" onClick={() => navigate("/compliance")}>
          Open Compliance
        </Button>
      </section>
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  loading,
  error,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  loading: boolean;
  error: boolean;
}) {
  return (
    <Metric
      label={label}
      value={loading ? <Skeleton lines={1} /> : error || value == null ? "Unavailable" : value}
      hint={loading ? undefined : error ? "Could not load — use Refresh" : hint}
    />
  );
}

function RiskBody({
  level,
  score,
  generatedMillis,
  insights,
}: {
  level: string;
  score: number;
  generatedMillis: number | null;
  insights: RiskInsight[];
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge
          tone={level === "critical" ? "danger" : level === "high" || level === "elevated" ? "warning" : level === "moderate" ? "info" : "success"}
          size="sm"
        >
          {level}
        </Badge>
        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {typeof score === "number" && Number.isFinite(score) ? formatNumber(score, 2) : "—"}
        </span>
        <span className="ml-auto text-[11px] text-slate-400">
          {generatedMillis != null ? formatRelative(generatedMillis) : null}
        </span>
      </div>
      {insights.length === 0 ? (
        <EmptyState title="No insights right now" description="Risk insights appear here when the engine raises them." />
      ) : (
        <ul className="space-y-2">
          {insights.slice(0, 5).map((insight) => (
            <li
              key={insight.insight_id}
              className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="flex items-center gap-2">
                <Badge
                  tone={insight.severity === "critical" ? "danger" : insight.severity === "warning" ? "warning" : "info"}
                  size="sm"
                >
                  {insight.severity}
                </Badge>
                <p className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-900 dark:text-slate-100">
                  {insight.title}
                </p>
              </div>
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{insight.description}</p>
              {insight.recommendation ? (
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  {insight.recommendation}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ImpactBar({
  counts,
  total,
  average,
}: {
  counts: Record<string, number>;
  total: number;
  average: number;
}) {
  const safeTotal = total ?? 0;
  const safeCounts = counts ?? {};
  const order = ["critical", "high", "medium", "low", "negligible"];
  const tones: Record<string, string> = {
    critical: "bg-red-500",
    high: "bg-amber-500",
    medium: "bg-sky-500",
    low: "bg-emerald-500",
    negligible: "bg-slate-400",
  };
  const summary = order
    .map((level) => `${level} ${safeCounts[level] ?? 0}`)
    .join(", ");
  return (
    <div>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        role="img"
        aria-label={`Impact distribution across ${safeTotal} reports: ${summary}`}
      >
        {order.map((level) => {
          const count = safeCounts[level] ?? 0;
          if (safeTotal <= 0 || count <= 0) return null;
          return (
            <div
              key={level}
              aria-hidden
              className={tones[level]}
              style={{ width: `${(count / safeTotal) * 100}%` }}
            />
          );
        })}
      </div>
      <ul className="mt-2 space-y-1">
        {order.map((level) => (
          <li key={level} className="flex items-center gap-2 text-xs">
            <span className="w-20 capitalize text-slate-500 dark:text-slate-400">{level}</span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {formatNumber(safeCounts[level] ?? 0)}
            </span>
          </li>
        ))}
      </ul>
      <p className="meta-text mt-2">
        {formatNumber(safeTotal)} reports · average score{" "}
        {typeof average === "number" && Number.isFinite(average) ? average.toFixed(2) : "—"}
      </p>
    </div>
  );
}

function latestValue(points: { value: number }[] | undefined): number {
  if (!points || points.length === 0) return 0;
  return points[points.length - 1].value;
}

