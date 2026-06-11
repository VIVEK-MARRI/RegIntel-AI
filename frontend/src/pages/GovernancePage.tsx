import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useDecisions, useGovernanceStats, usePolicies } from "@/hooks/api";
import { useDemoQuery } from "@/hooks/useDemoFallback";
import { demoDecisions, demoGovernanceStats, demoPolicies } from "@/lib/demo";
import { formatRelative, truncate } from "@/lib/format";

export function GovernancePage() {
  const policies = useDemoQuery("Governance", demoPolicies, usePolicies);
  const decisions = useDemoQuery("Governance", demoDecisions, useDecisions);
  const stats = useDemoQuery("Governance", demoGovernanceStats, useGovernanceStats);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Governance Center
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          AI policies, decision logs, and human-in-the-loop approvals.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Policies"
          value={stats.data?.total_policies ?? "—"}
          hint="Active governance"
        />
        <Metric
          label="Decisions"
          value={stats.data?.total_decisions ?? "—"}
          hint="Logged outcomes"
        />
        <Metric
          label="Active"
          value={stats.data?.active ?? "—"}
        />
        <Metric
          label="Deprecated"
          value={stats.data?.deprecated ?? "—"}
        />
      </section>

      <Card padding="none">
        <CardHeader
          title="Policies"
          description="All governance policies"
        />
        <div className="card-body">
          {policies.isLoading ? (
            <Skeleton lines={4} />
          ) : policies.isError ? (
            <ErrorState error={policies.error} onRetry={() => policies.refetch()} />
          ) : !policies.data || policies.data.length === 0 ? (
            <EmptyState title="No policies defined" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Scope</TH>
                  <TH>Status</TH>
                  <TH>Rules</TH>
                  <TH>Updated</TH>
                </TR>
              </THead>
              <TBody>
                {policies.data.map((p) => (
                  <TR key={p.policy_id}>
                    <TD>
                      <p className="font-semibold text-slate-900 dark:text-slate-100">
                        {p.name}
                      </p>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400">
                        {truncate(p.description, 120)}
                      </p>
                    </TD>
                    <TD>{p.scope}</TD>
                    <TD>
                      <Badge
                        tone={
                          p.status === "active"
                            ? "success"
                            : p.status === "draft"
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {p.status}
                      </Badge>
                    </TD>
                    <TD>{p.rules?.length ?? 0}</TD>
                    <TD>{formatRelative(p.updated_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader
          title="Decisions"
          description="Recent governance decisions"
        />
        <div className="card-body">
          {decisions.isLoading ? (
            <Skeleton lines={4} />
          ) : decisions.isError ? (
            <ErrorState error={decisions.error} onRetry={() => decisions.refetch()} />
          ) : !decisions.data?.items?.length ? (
            <EmptyState title="No decisions yet" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Type</TH>
                  <TH>Subject</TH>
                  <TH>Outcome</TH>
                  <TH>Confidence</TH>
                  <TH>Approver</TH>
                  <TH>Created</TH>
                </TR>
              </THead>
              <TBody>
                {decisions.data.items.map((d) => (
                  <TR key={d.decision_id}>
                    <TD>
                      <Badge tone="brand" size="sm">
                        {d.decision_type}
                      </Badge>
                    </TD>
                    <TD>{truncate(d.subject, 80)}</TD>
                    <TD>{d.outcome}</TD>
                    <TD>{(d.confidence * 100).toFixed(0)}%</TD>
                    <TD>{d.approver ?? "—"}</TD>
                    <TD>{formatRelative(d.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </Card>
    </div>
  );
}
