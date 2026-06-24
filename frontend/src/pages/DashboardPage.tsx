import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { useQuery } from "@tanstack/react-query";
import { getAnalyticsOverview, getChanges } from "@/services/api/analyticsApi";
import { getDocuments } from "@/services/api/documentsApi";
import { getResearchReports } from "@/services/api/researchApi";
import { getGovernanceStats } from "@/services/api/governanceApi";
import { formatRelative } from "@/lib/format";
import { useNavigate } from "react-router-dom";

export function DashboardPage() {
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ["dashboard", "overview"], queryFn: getAnalyticsOverview });
  const changes = useQuery({ queryKey: ["dashboard", "changes"], queryFn: getChanges });
  const docs = useQuery({ queryKey: ["dashboard", "documents"], queryFn: getDocuments });
  const reports = useQuery({ queryKey: ["dashboard", "reports"], queryFn: getResearchReports });
  const policies = useQuery({ queryKey: ["dashboard", "governance-stats"], queryFn: getGovernanceStats });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      {/* What changed — top KPIs */}
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Documents Indexed</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            {docs.data?.filter((d) => d.status === "INDEXED").length ?? "—"}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">{docs.data?.length ?? 0} total documents</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Open Reviews</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            {policies.data?.total_decisions ?? "—"}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">Pending governance decisions</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Recent Changes</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
            {changes.data?.length ?? 0}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">Regulatory updates</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">System Health</p>
          <p className="mt-1 text-2xl font-semibold text-emerald-600 dark:text-emerald-400">
            {overview.data?.health?.overall_health ?? "—"}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">{overview.data?.total_agents ?? 0} agents active</p>
        </div>
      </section>

      {/* Primary CTAs */}
      <section className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => navigate("/documents")}
          className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          Upload Document
        </button>
        <button
          type="button"
          onClick={() => navigate("/copilot")}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          Ask Copilot
        </button>
      </section>

      {/* What needs attention — recent activity */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Recent Regulatory Changes"
            actions={
              <button type="button" onClick={() => navigate("/compliance")} className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300">View all →</button>
            }
          />
          <div className="card-body">
            {changes.isLoading ? <Skeleton lines={4} />
            : changes.isError ? <ErrorState error={changes.error} onRetry={() => changes.refetch()} />
            : !changes.data || changes.data.length === 0 ? <EmptyState title="No recent changes" description="Regulatory updates will appear here." />
            : <ul className="space-y-2">
                {changes.data.slice(0, 5).map((c) => (
                  <li key={c.change_id} className="flex items-center gap-2 text-xs">
                    <Badge tone={c.change_type === "added" ? "success" : c.change_type === "modified" ? "info" : "danger"} size="sm">{c.change_type}</Badge>
                    <span className="truncate text-slate-700 dark:text-slate-200">{c.summary}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400">{formatRelative(c.detected_at)}</span>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Recent Uploads"
            actions={
              <button type="button" onClick={() => navigate("/documents")} className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300">View all →</button>
            }
          />
          <div className="card-body">
            {docs.isLoading ? <Skeleton lines={4} />
            : docs.isError ? <ErrorState error={docs.error} onRetry={() => docs.refetch()} />
            : !docs.data || docs.data.length === 0 ? <EmptyState title="No documents yet" description="Upload a document to get started." />
            : <ul className="space-y-2">
                {docs.data.slice(0, 5).map((d) => (
                  <li key={d.id} className="flex items-center gap-2 text-xs">
                    <Badge tone={d.status === "INDEXED" ? "success" : d.status === "FAILED" ? "danger" : "warning"} size="sm">{d.status}</Badge>
                    <span className="truncate text-slate-700 dark:text-slate-200">{d.title}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400">{formatRelative(d.created_at)}</span>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Recent Research Reports"
            actions={
              <button type="button" onClick={() => navigate("/research")} className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300">View all →</button>
            }
          />
          <div className="card-body">
            {reports.isLoading ? <Skeleton lines={4} />
            : reports.isError ? <ErrorState error={reports.error} onRetry={() => reports.refetch()} />
            : !reports.data || reports.data.length === 0 ? <EmptyState title="No research yet" description="Run a research query to generate reports." />
            : <ul className="space-y-2">
                {reports.data.slice(0, 5).map((r) => (
                  <li key={r.report_id} className="flex items-center gap-2 text-xs">
                    <span className="truncate font-medium text-slate-900 dark:text-slate-100">{r.summary || r.query}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400">{formatRelative(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Recent Governance Actions"
            actions={
              <button type="button" onClick={() => navigate("/compliance")} className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-300">View all →</button>
            }
          />
          <div className="card-body">
            {policies.isLoading ? <Skeleton lines={4} />
            : policies.isError ? <ErrorState error={policies.error} onRetry={() => policies.refetch()} />
            : !policies.data ? <EmptyState title="No governance activity" />
            : <ul className="space-y-2">
                <li key="policies" className="flex items-center gap-2 text-xs"><span className="text-slate-500">{policies.data.total_policies ?? 0} policies</span></li>
                <li key="decisions" className="flex items-center gap-2 text-xs"><span className="text-slate-500">{policies.data.total_decisions ?? 0} decisions recorded</span></li>
                <li key="active" className="flex items-center gap-2 text-xs"><span className="text-slate-500">{policies.data.active ?? 0} active</span></li>
              </ul>
            }
          </div>
        </Card>
      </section>
    </div>
  );
}
