import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useQuery } from "@tanstack/react-query";
import { getPolicies, getDecisions, getGovernanceStats } from "@/services/api/governanceApi";
import { formatRelative, truncate } from "@/lib/format";

export function GovernancePage() {
  const { data: policies, isLoading: pLoading, isError: pError, refetch: pRefetch } = useQuery({
    queryKey: ["governance", "policies"], queryFn: getPolicies,
  });
  const { data: decisions, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: ["governance", "decisions"], queryFn: getDecisions,
  });
  const { data: stats, isLoading: sLoading, isError: sError, refetch: sRefetch } = useQuery({
    queryKey: ["governance", "stats"], queryFn: getGovernanceStats,
  });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Governance</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Policy decisions, approvals, escalations, and audit reviews.</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        {sLoading ? Array.from({length: 4}).map((_, i) => (<Metric key={i} label="—" value="…" />))
        : sError ? <ErrorState onRetry={sRefetch} />
        : <>
            <Metric label="Policies" value={stats?.total_policies ?? "—"} />
            <Metric label="Active" value={stats?.active ?? "—"} hint="Active policies" />
            <Metric label="Decisions" value={stats?.total_decisions ?? "—"} />
            <Metric label="Deprecated" value={stats?.deprecated ?? "—"} />
          </>
        }
      </section>

      <Card padding="none">
        <CardHeader title="Policies" />
        <div className="card-body">
          {pLoading ? <Skeleton lines={4} />
          : pError ? <ErrorState onRetry={pRefetch} />
          : !policies?.length ? <EmptyState title="No policies defined" />
          : <Table>
              <THead><TR><TH>Name</TH><TH>Scope</TH><TH>Status</TH><TH>Version</TH><TH>Rules</TH><TH>Updated</TH></TR></THead>
              <TBody>
                {policies.map((p) => (
                  <TR key={p.policy_id}>
                    <TD className="font-medium">{p.name}</TD>
                    <TD className="text-slate-500">{truncate(p.scope, 60)}</TD>
                    <TD><Badge tone={p.status === "active" ? "success" : p.status === "deprecated" ? "danger" : "warning"} size="sm">{p.status}</Badge></TD>
                    <TD>v{p.version}</TD>
                    <TD>{p.rules.length}</TD>
                    <TD className="text-slate-500">{formatRelative(p.updated_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          }
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Decisions" />
        <div className="card-body">
          {dLoading ? <Skeleton lines={4} />
          : dError ? <ErrorState onRetry={dRefetch} />
          : !decisions?.length ? <EmptyState title="No decisions recorded" />
          : <Table>
              <THead><TR><TH>Type</TH><TH>Subject</TH><TH>Outcome</TH><TH>Confidence</TH><TH>Approver</TH><TH>When</TH></TR></THead>
              <TBody>
                {decisions.map((d) => (
                  <TR key={d.decision_id}>
                    <TD><Badge tone="brand" size="sm">{d.decision_type}</Badge></TD>
                    <TD>{truncate(d.subject, 80)}</TD>
                    <TD>{d.outcome}</TD>
                    <TD>{Math.round(d.confidence * 100)}%</TD>
                    <TD>{d.approver ?? "—"}</TD>
                    <TD className="text-slate-500">{formatRelative(d.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          }
        </div>
      </Card>
    </div>
  );
}
