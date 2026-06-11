import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { ProgressBar } from "@/components/ui/ProgressBar";
import {
  useAuditEvidence,
  useAuditIntegrity,
  useAuditRecords,
  useAuditReports,
} from "@/hooks/api";
import { useDemoQuery } from "@/hooks/useDemoFallback";
import {
  demoAuditEvidence,
  demoAuditIntegrity,
  demoAuditRecords,
  demoAuditReports,
} from "@/lib/demo";
import { formatRelative, truncate } from "@/lib/format";

export function AuditPage() {
  const records = useDemoQuery("Audit", demoAuditRecords, useAuditRecords);
  const integrity = useDemoQuery("Audit", demoAuditIntegrity, useAuditIntegrity);
  const evidence = useDemoQuery("Audit", demoAuditEvidence, useAuditEvidence);
  const reports = useDemoQuery("Audit", demoAuditReports, useAuditReports);

  const integrityPct = integrity.data
    ? (integrity.data.valid / Math.max(1, integrity.data.total)) * 100
    : 0;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Audit Console
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Tamper-evident audit log, evidence, and reports.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Total records"
          value={records.data?.total ?? "—"}
        />
        <Metric
          label="Valid"
          value={integrity.data?.valid ?? "—"}
          hint="Cryptographically valid"
        />
        <Metric
          label="Broken chains"
          value={integrity.data?.broken_chains.length ?? 0}
          hint="Requires attention"
        />
        <Metric
          label="Evidence items"
          value={evidence.data?.length ?? "—"}
        />
      </section>

      <Card padding="none">
        <CardHeader
          title="Chain integrity"
          description="Cryptographic audit chain health"
        />
        <div className="card-body">
          {integrity.isLoading ? (
            <Skeleton lines={3} />
          ) : integrity.isError ? (
            <ErrorState
              error={integrity.error}
              onRetry={() => integrity.refetch()}
            />
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs">
                <Badge
                  tone={
                    (integrity.data?.broken_chains.length ?? 0) === 0
                      ? "success"
                      : "danger"
                  }
                >
                  {(integrity.data?.broken_chains.length ?? 0) === 0
                    ? "Healthy"
                    : "Compromised"}
                </Badge>
                <span className="text-slate-500 dark:text-slate-400">
                  Last check: {formatRelative(integrity.data?.checked_at)}
                </span>
              </div>
              <ProgressBar
                value={integrityPct}
                tone={integrityPct > 99 ? "success" : integrityPct > 90 ? "warning" : "danger"}
                showLabel
              />
            </div>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Records" description="Recent audit records" />
        <div className="card-body">
          {records.isLoading ? (
            <Skeleton lines={5} />
          ) : records.isError ? (
            <ErrorState error={records.error} onRetry={() => records.refetch()} />
          ) : !records.data?.items?.length ? (
            <EmptyState title="No audit records" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Actor</TH>
                  <TH>Action</TH>
                  <TH>Subject</TH>
                  <TH>Outcome</TH>
                  <TH>Evidence</TH>
                  <TH>When</TH>
                </TR>
              </THead>
              <TBody>
                {records.data.items.slice(0, 20).map((r) => (
                  <TR key={r.audit_id}>
                    <TD>{r.actor}</TD>
                    <TD>
                      <Badge tone="brand" size="sm">
                        {r.action}
                      </Badge>
                    </TD>
                    <TD>{truncate(r.subject, 80)}</TD>
                    <TD>{r.outcome}</TD>
                    <TD>{r.evidence_ids.length}</TD>
                    <TD>{formatRelative(r.timestamp)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Compliance reports" description="Generated reports" />
        <div className="card-body">
          {reports.isLoading ? (
            <Skeleton lines={3} />
          ) : !reports.data || reports.data.length === 0 ? (
            <EmptyState title="No reports" />
          ) : (
            <ul className="space-y-2">
              {reports.data.map((r) => (
                <li
                  key={r.report_id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {r.title}
                    </span>
                    <Badge tone={r.status === "published" ? "success" : "warning"}>
                      {r.status}
                    </Badge>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {formatRelative(r.generated_at)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {r.period_start} – {r.period_end} · {r.sections.length} sections
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
