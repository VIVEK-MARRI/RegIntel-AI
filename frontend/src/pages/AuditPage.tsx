import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useQuery } from "@tanstack/react-query";
import { getAuditRecords, getAuditIntegrity, getAuditEvidence, getAuditReports } from "@/services/api/auditApi";
import { formatRelative, truncate } from "@/lib/format";

export function AuditPage() {
  const { data: records, isLoading: rLoading, isError: rError, refetch: rRefetch } = useQuery({
    queryKey: ["audit", "records"], queryFn: getAuditRecords,
  });
  const { data: integrity, isLoading: iLoading, isError: iError, refetch: iRefetch } = useQuery({
    queryKey: ["audit", "integrity"], queryFn: getAuditIntegrity,
  });
  const { data: evidence, isLoading: eLoading, isError: eError } = useQuery({
    queryKey: ["audit", "evidence"], queryFn: getAuditEvidence,
  });
  const { data: reports, isLoading: repLoading, isError: repError } = useQuery({
    queryKey: ["audit", "reports"], queryFn: getAuditReports,
  });

  const [tab, setTab] = useState<"records" | "reports" | "evidence">("records");

  const integrityPct = integrity ? (integrity.valid / Math.max(1, integrity.total)) * 100 : 0;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Audit</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Tamper-evident audit trail, evidence explorer, and decision lineage.</p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Total records" value={records?.length ?? "—"} />
        <Metric label="Valid" value={integrity?.valid ?? "—"} hint="Cryptographically valid" />
        <Metric label="Broken chains" value={integrity?.broken_chains?.length ?? 0} hint="Requires attention" />
        <Metric label="Evidence items" value={evidence?.length ?? "—"} />
      </section>

      <Card padding="none">
        <CardHeader title="Chain integrity" description="Cryptographic audit chain health" />
        <div className="card-body">
          {iLoading ? <Skeleton lines={3} />
          : iError ? <ErrorState onRetry={iRefetch} />
          : <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs">
                <Badge tone={!integrity?.broken_chains?.length ? "success" : "danger"}>
                  {!integrity?.broken_chains?.length ? "Healthy" : "Compromised"}
                </Badge>
                <span className="text-slate-500 dark:text-slate-400">Last check: {formatRelative(integrity?.checked_at)}</span>
              </div>
              <ProgressBar value={integrityPct} tone={integrityPct > 99 ? "success" : integrityPct > 90 ? "warning" : "danger"} showLabel />
            </div>
          }
        </div>
      </Card>

      <div className="flex gap-2 border-b border-slate-200 dark:border-slate-800">
        {(["records", "reports", "evidence"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`px-4 py-2 text-xs font-medium transition border-b-2 -mb-px ${
              tab === t
                ? "border-brand-500 text-brand-700 dark:text-brand-300"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            }`}
          >{t.charAt(0).toUpperCase() + t.slice(1)}</button>
        ))}
      </div>

      {tab === "records" ? (
        <Card padding="none">
          <CardHeader title="Records" description="Recent audit records" />
          <div className="card-body">
            {rLoading ? <Skeleton lines={5} />
            : rError ? <ErrorState onRetry={rRefetch} />
            : !records?.length ? <EmptyState title="No audit records" />
            : <Table>
                <THead><TR><TH>Actor</TH><TH>Action</TH><TH>Subject</TH><TH>Outcome</TH><TH>Evidence</TH><TH>When</TH></TR></THead>
                <TBody>
                  {records.slice(0, 50).map((r) => (
                    <TR key={r.audit_id}>
                      <TD>{r.actor}</TD>
                      <TD><Badge tone="brand" size="sm">{r.action}</Badge></TD>
                      <TD>{truncate(r.subject, 80)}</TD>
                      <TD>{r.outcome}</TD>
                      <TD>{(r.evidence_ids?.length ?? 0)}</TD>
                      <TD>{formatRelative(r.timestamp)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            }
          </div>
        </Card>
      ) : tab === "reports" ? (
        <Card padding="none">
          <CardHeader title="Compliance reports" description="Generated reports" />
          <div className="card-body">
            {repLoading ? <Skeleton lines={3} />
            : repError ? <ErrorState />
            : !reports?.length ? <EmptyState title="No reports" />
            : <ul className="space-y-2">
                {reports.map((r) => (
                  <li key={r.report_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{r.title}</span>
                      <Badge tone={r.status === "published" ? "success" : "warning"} size="sm">{r.status}</Badge>
                      <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">{formatRelative(r.generated_at)}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{r.period_start} – {r.period_end} · {(r.sections?.length ?? 0)} sections</p>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>
      ) : (
        <Card padding="none">
          <CardHeader title="Evidence" description="Collected audit evidence" />
          <div className="card-body">
            {eLoading ? <Skeleton lines={3} />
            : eError ? <ErrorState />
            : !evidence?.length ? <EmptyState title="No evidence items" />
            : <Table>
                <THead><TR><TH>ID</TH><TH>Kind</TH><TH>Audit ID</TH><TH>Signature</TH><TH>Created</TH></TR></THead>
                <TBody>
                  {evidence.map((e) => (
                    <TR key={e.evidence_id}>
                      <TD className="font-mono text-[10px]">{truncate(e.evidence_id, 16)}</TD>
                      <TD><Badge tone="neutral" size="sm">{e.kind}</Badge></TD>
                      <TD className="font-mono text-[10px]">{truncate(e.audit_id, 16)}</TD>
                      <TD className="font-mono text-[10px] text-slate-500">{truncate(e.signature, 16)}</TD>
                      <TD className="text-slate-500">{formatRelative(e.created_at)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            }
          </div>
        </Card>
      )}
    </div>
  );
}
