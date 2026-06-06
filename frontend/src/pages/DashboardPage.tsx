import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import {
  useAlerts,
  useAnalyticsOverview,
  useAuditIntegrity,
  useChanges,
  useComplianceAssessments,
  useDocuments,
  useGovernanceStats,
  useIntelligenceMetrics,
  useLeaderboard,
  useRecommendations,
  useReviewTasks,
  useRiskForecasts,
} from "@/hooks/api";
import { formatRelative, formatPercent, formatNumber } from "@/lib/format";
import { useNavigate } from "react-router-dom";

export function DashboardPage() {
  const navigate = useNavigate();
  const overview = useAnalyticsOverview();
  const metrics = useIntelligenceMetrics();
  const policies = useGovernanceStats();
  const compliance = useComplianceAssessments();
  const risks = useRiskForecasts();
  const recs = useRecommendations();
  const reviews = useReviewTasks();
  const alerts = useAlerts();
  const changes = useChanges();
  const integrity = useAuditIntegrity();
  const docs = useDocuments();
  const leaderboard = useLeaderboard(5);

  const overallHealth = overview.data?.health.overall_health ?? "unknown";
  const complianceScore =
    compliance.data && compliance.data.length
      ? Math.round(
          (compliance.data.reduce((s, a) => s + a.overall_score, 0) /
            compliance.data.length) *
            100
        )
      : null;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
          Welcome back, Vivek
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          A unified view of regulatory intelligence, agent performance, and platform health.
        </p>
      </header>

      <section
        aria-label="Key metrics"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Metric
          label="Active Agents"
          value={overview.data ? overview.data.total_agents : "—"}
          hint={
            metrics.data
              ? `${metrics.data.total_invocations.toLocaleString()} invocations`
              : "Loading…"
          }
          icon={<span aria-hidden>◍</span>}
        />
        <Metric
          label="System Health"
          value={
            <span className="capitalize">{overallHealth}</span>
          }
          hint={overview.data?.health.notes ?? "No data"}
          icon={<span aria-hidden>♥</span>}
        />
        <Metric
          label="Compliance Score"
          value={complianceScore !== null ? `${complianceScore}%` : "—"}
          hint={
            compliance.data
              ? `${compliance.data.length} assessment${compliance.data.length === 1 ? "" : "s"}`
              : "Loading…"
          }
          icon={<span aria-hidden>✓</span>}
        />
        <Metric
          label="Audit Integrity"
          value={
            integrity.data
              ? `${Math.round(
                  (integrity.data.valid / Math.max(1, integrity.data.total)) * 100
                )}%`
              : "—"
          }
          hint={
            integrity.data
              ? `${integrity.data.valid.toLocaleString()} / ${integrity.data.total.toLocaleString()} valid`
              : "Loading…"
          }
          icon={<span aria-hidden>⛬</span>}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card padding="none" className="lg:col-span-2">
          <CardHeader
            title="Risk Forecast"
            description="Projected risk over the next 30 days"
            actions={
              <button
                type="button"
                onClick={() => navigate("/risk")}
                className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                View all →
              </button>
            }
          />
          <div className="card-body">
            {risks.isLoading ? (
              <Skeleton lines={4} />
            ) : risks.isError ? (
              <ErrorState error={risks.error} onRetry={() => risks.refetch()} />
            ) : !risks.data || risks.data.length === 0 ? (
              <EmptyState
                title="No forecasts yet"
                description="Generate a forecast to see projected risk scores."
              />
            ) : (
              <ul className="space-y-3">
                {risks.data.slice(0, 4).map((r) => (
                  <li key={r.forecast_id} className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium text-slate-700 dark:text-slate-200">
                          {r.horizon_days}-day horizon
                        </span>
                        <span className="text-slate-500 dark:text-slate-400">
                          {formatNumber(r.projected_score)} / 100
                        </span>
                      </div>
                      <ProgressBar
                        value={r.projected_score}
                        max={100}
                        tone={
                          r.projected_score > 75
                            ? "danger"
                            : r.projected_score > 50
                              ? "warning"
                              : "success"
                        }
                        className="mt-1.5"
                      />
                    </div>
                    <Badge tone={r.confidence > 0.75 ? "success" : "warning"}>
                      {(r.confidence * 100).toFixed(0)}% conf
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader
            title="Open Alerts"
            actions={
              <button
                type="button"
                onClick={() => navigate("/agents")}
                className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                View all →
              </button>
            }
          />
          <div className="card-body">
            {alerts.isLoading ? (
              <Skeleton lines={4} />
            ) : alerts.isError ? (
              <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
            ) : !alerts.data || alerts.data.length === 0 ? (
              <EmptyState title="No open alerts" description="All clear." />
            ) : (
              <ul className="space-y-2.5">
                {alerts.data.slice(0, 4).map((a) => (
                  <li
                    key={a.alert_id}
                    className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
                  >
                    <Badge
                      tone={
                        a.severity === "critical"
                          ? "danger"
                          : a.severity === "warning"
                            ? "warning"
                            : "info"
                      }
                      size="sm"
                    >
                      {a.severity}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-slate-900 dark:text-slate-100">
                        {a.title}
                      </p>
                      <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">
                        {a.source} • {formatRelative(a.detected_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card padding="none">
          <CardHeader
            title="Top Agents"
            actions={
              <button
                type="button"
                onClick={() => navigate("/agents")}
                className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                Leaderboard →
              </button>
            }
          />
          <div className="card-body">
            {leaderboard.isLoading ? (
              <Skeleton lines={4} />
            ) : !leaderboard.data || leaderboard.data.length === 0 ? (
              <EmptyState
                title="No agent activity"
                description="Run an agent to see the leaderboard populate."
              />
            ) : (
              <ol className="space-y-2">
                {leaderboard.data.slice(0, 5).map((entry) => (
                  <li
                    key={entry.agent_name}
                    className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/40"
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">
                      {entry.rank}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-slate-900 dark:text-slate-100">
                        {entry.agent_name}
                      </p>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400">
                        {formatPercent(entry.success_rate)} success • {entry.invocations} invocations
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-brand-600 dark:text-brand-300">
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
            title="Recent Changes"
            actions={
              <button
                type="button"
                onClick={() => navigate("/knowledge-graph")}
                className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                Knowledge Graph →
              </button>
            }
          />
          <div className="card-body">
            {changes.isLoading ? (
              <Skeleton lines={4} />
            ) : !changes.data || changes.data.length === 0 ? (
              <EmptyState
                title="No recent changes"
                description="Document changes will appear here."
              />
            ) : (
              <ul className="space-y-2">
                {changes.data.slice(0, 5).map((c) => (
                  <li key={c.change_id} className="flex items-center gap-2 text-xs">
                    <Badge
                      tone={
                        c.change_type === "added"
                          ? "success"
                          : c.change_type === "modified"
                            ? "info"
                            : "danger"
                      }
                      size="sm"
                    >
                      {c.change_type}
                    </Badge>
                    <span className="truncate text-slate-700 dark:text-slate-200">
                      {c.summary}
                    </span>
                    <span className="ml-auto text-[11px] text-slate-500 dark:text-slate-400">
                      {formatRelative(c.detected_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader
            title="Recommendations"
            actions={
              <button
                type="button"
                onClick={() => navigate("/compliance")}
                className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                Open →
              </button>
            }
          />
          <div className="card-body">
            {recs.isLoading ? (
              <Skeleton lines={4} />
            ) : !recs.data || recs.data.length === 0 ? (
              <EmptyState
                title="No recommendations"
                description="New suggestions will appear here."
              />
            ) : (
              <ul className="space-y-2">
                {recs.data.slice(0, 4).map((r) => (
                  <li
                    key={r.recommendation_id}
                    className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
                  >
                    <div className="flex items-center gap-2">
                      <Badge tone="brand" size="sm">
                        {r.priority}
                      </Badge>
                      <span className="truncate text-xs font-medium text-slate-900 dark:text-slate-100">
                        {r.title}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] text-slate-500 dark:text-slate-400">
                      {r.description}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader
            title="Pending Reviews"
            actions={
              <Badge tone="warning">
                {reviews.data?.filter((r) => r.status === "pending").length ?? 0}
              </Badge>
            }
          />
          <div className="card-body">
            {reviews.isLoading ? (
              <Skeleton lines={3} />
            ) : !reviews.data || reviews.data.length === 0 ? (
              <EmptyState title="No pending reviews" />
            ) : (
              <ul className="space-y-2">
                {reviews.data.slice(0, 4).map((t) => (
                  <li
                    key={t.task_id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-slate-900 dark:text-slate-100">
                        {t.subject}
                      </p>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400">
                        Reviewer: {t.reviewer}
                      </p>
                    </div>
                    <Badge
                      tone={
                        t.status === "approved"
                          ? "success"
                          : t.status === "rejected"
                            ? "danger"
                            : "warning"
                      }
                      size="sm"
                    >
                      {t.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader
            title="Governance & Documents"
            description="Policy coverage and document footprint"
          />
          <div className="card-body grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Policies
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {policies.data?.total_policies ?? "—"}
              </p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Documents
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {docs.data?.total ?? "—"}
              </p>
            </div>
            <div className="col-span-2 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Governance Decisions
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {policies.data?.total_decisions ?? "—"}
              </p>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
