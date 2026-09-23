import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Input, Select } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/providers/ToastProvider";
import { formatDate, formatRelative } from "@/lib/format";
import { toMillis } from "@/lib/dates";
import { auditKeys } from "@/lib/queryKeys";
import {
  generateAuditReport,
  getAuditEvidence,
  getAuditEvidenceById,
  getAuditIntegrity,
  getAuditRecord,
  getAuditRecords,
  getAuditReports,
  getAuditStats,
} from "@/services/api/auditApi";
import type {
  AuditEvidence,
  AuditRecord,
  ComplianceReport,
  ReportSection,
} from "@/types/api/audit";

/**
 * Audit evidence workspace: records, hash-chain integrity, evidence, reports.
 *
 * Trust rules enforced here (backend-verified):
 * - Integrity states are tri-state: intact / compromised / unavailable. The
 *   backend exposes {intact, message, counts} with NO checked-at timestamp —
 *   none is shown. "Intact" means hash-chain linkage + per-record SHA-256
 *   recomputation verified, nothing more ("tamper-proof" is never claimed).
 * - Records arrive oldest-first by chain sequence; the list says so and never
 *   calls them "recent". Totals come from /stats, never from rendered rows.
 * - Records carry NO outcome field — none is displayed.
 * - Evidence content dicts render scalar fields only; hashes are shown
 *   verbatim (never called encryption) with copy affordances.
 * - No export UI exists: the backend offers no export endpoint.
 */

type TabId = "records" | "evidence" | "reports";

const TABS = [
  { id: "records" as const, label: "Records" },
  { id: "evidence" as const, label: "Evidence" },
  { id: "reports" as const, label: "Reports" },
];

const ACTIONS = [
  "create", "update", "delete", "read", "login", "logout", "export",
  "approve", "reject", "escalate", "policy_check", "workflow_start",
  "workflow_complete", "report_generate", "config_change", "rbac_grant",
  "rbac_revoke", "other",
];
const SEVERITIES = ["info", "notice", "warning", "error", "critical"];
const REPORT_KINDS = [
  "regulatory_submission", "internal_audit", "policy_attestation",
  "incident_summary", "evidence_bundle", "custom",
];

const PAGE_SIZE = 50;

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
function severityTone(s: string): Tone {
  switch (s) {
    case "critical": return "danger";
    case "error": return "danger";
    case "warning": return "warning";
    case "notice": return "neutral";
    case "info": return "info";
    default: return "neutral";
  }
}
function reportStatusTone(s: string): Tone {
  switch (s) {
    case "complete": return "success";
    case "failed": return "danger";
    case "generating": return "info";
    default: return "neutral";
  }
}

/** Runtime guards: backend shapes are trusted but never assumed. */
function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function scalarEntries(v: unknown): [string, string][] {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return [];
  const out: [string, string][] = [];
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (typeof val === "string" || typeof val === "number" || typeof val === "boolean") {
      out.push([k, String(val)]);
    }
  }
  return out;
}
/** datetime-local input value → epoch seconds (or undefined when empty/invalid). */
function fromInputValue(v: string): number | undefined {
  const t = v.trim();
  if (!t) return undefined;
  const ms = Date.parse(t);
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}
function shortHash(h: string): string {
  return h.length > 20 ? `${h.slice(0, 12)}…${h.slice(-6)}` : h;
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  return (
    <button
      type="button"
      aria-label={label}
      title={value}
      onClick={() => {
        try {
          const done = () => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          };
          const clip = navigator.clipboard;
          if (clip && typeof clip.writeText === "function") {
            void clip.writeText(value).then(done).catch(() => setCopied(false));
          }
        } catch {
          setCopied(false);
        }
      }}
      className="ml-1 rounded border border-slate-200 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

function HashValue({ value }: { value: string }) {
  if (!value) return <span className="meta-text">none recorded</span>;
  return (
    <span className="font-mono text-[11px] text-slate-600 dark:text-slate-300">
      <span title={value}>{shortHash(value)}</span>
      <CopyButton value={value} label={`Copy full hash ${value.slice(0, 12)}`} />
    </span>
  );
}

export function AuditPage() {
  const [tab, setTab] = useState<TabId>("records");
  const [recordId, setRecordId] = useState<string | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  const openRecord = (id: string) => {
    setRecordId(id);
    setTab("records");
  };
  const openEvidence = (id: string) => {
    setEvidenceId(id);
    setTab("evidence");
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Audit</h1>
        <p className="page-description">
          Records of what happened, hash-chain integrity status, associated
          evidence, and compliance reports.
        </p>
      </header>

      <IntegrityBanner />

      <StatsRow />

      <Tabs
        items={TABS}
        value={tab}
        onChange={(id) => setTab(id as TabId)}
        label="Audit sections"
        idPrefix="audit"
      />

      <div role="tabpanel" id={`audit-panel-${tab}`} aria-labelledby={`audit-tab-${tab}`} tabIndex={0}>
        {tab === "records" && <RecordsTab recordId={recordId} onSelectRecord={setRecordId} onOpenEvidence={openEvidence} />}
        {tab === "evidence" && <EvidenceTab evidenceId={evidenceId} onSelectEvidence={setEvidenceId} onOpenRecord={openRecord} />}
        {tab === "reports" && <ReportsTab onOpenRecord={openRecord} onOpenEvidence={openEvidence} />}
      </div>
    </div>
  );
}

/* ─── integrity banner (always visible, first) ─────────────────────── */

function IntegrityBanner() {
  const integrity = useQuery({ queryKey: auditKeys.integrity(), queryFn: getAuditIntegrity });

  if (integrity.isPending) {
    return (
      <div aria-label="Integrity check loading">
        <Skeleton className="h-24" />
      </div>
    );
  }

  if (integrity.isError) {
    return (
      <Alert tone="warning" title="Integrity status unavailable">
        <p className="mt-1 text-sm">
          The integrity check itself could not be completed. This is NOT the same
          as an intact chain — no claim is made about the audit trail below.
        </p>
        <Button variant="ghost" size="sm" className="mt-2" onClick={() => void integrity.refetch()}>
          Retry integrity check
        </Button>
      </Alert>
    );
  }

  const d = integrity.data;
  if (d.intact) {
    return (
      <Alert tone="success" title="Audit-chain integrity check: intact.">
        <p className="mt-1 text-sm">
          Hash-chain linkage and per-record hashes verified for {d.total} record(s)
          ({d.valid} valid, {d.invalid} invalid) · chain length {d.chain_length}.
          {d.message ? ` Backend note: ${d.message}` : ""}
        </p>
        {d.last_chain_hash && (
          <p className="meta-text mt-1">
            Head hash: <HashValue value={d.last_chain_hash} />
          </p>
        )}
      </Alert>
    );
  }

  return (
    <Alert tone="danger" title="Audit-chain integrity check FAILED.">
      <p className="mt-1 text-sm font-medium">
        The audit chain does not verify. Treat records below as untrusted until
        this is resolved.
      </p>
      {d.message && <p className="mt-1 font-mono text-xs">{d.message}</p>}
      <p className="meta-text mt-1">
        Checked {d.total} record(s): {d.valid} valid, {d.invalid} invalid · chain
        length {d.chain_length}.
      </p>
    </Alert>
  );
}

function StatsRow() {
  const stats = useQuery({ queryKey: auditKeys.stats(), queryFn: getAuditStats });
  if (stats.isPending) {
    return (
      <section aria-label="Audit overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </section>
    );
  }
  if (stats.isError) {
    return (
      <ErrorState title="Audit statistics unavailable" error={stats.error} onRetry={() => void stats.refetch()} />
    );
  }
  const bySev = stats.data.by_severity ?? {};
  const attention = (Number(bySev.error ?? 0) || 0) + (Number(bySev.critical ?? 0) || 0);
  return (
    <section aria-label="Audit overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Metric label="Stored records" value={stats.data.total_records.toLocaleString()} hint="Backend total, not page size" />
      <Metric label="Chain length" value={stats.data.chain_length.toLocaleString()} hint="Hash-chain sequence length" />
      <Metric label="Error / critical records" value={attention.toLocaleString()} hint="Backend severity counts" />
      <Metric
        label="Last record"
        value={stats.data.last_record_at ? formatRelative(stats.data.last_record_at) : "—"}
        hint="Latest event time (backend maximum)"
      />
    </section>
  );
}

/* ─── records tab ──────────────────────────────────────────────────── */

function RecordsTab({
  recordId,
  onSelectRecord,
  onOpenEvidence,
}: {
  recordId: string | null;
  onSelectRecord: (id: string | null) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const [action, setAction] = useState("");
  const [severity, setSeverity] = useState("");
  const [actor, setActor] = useState("");
  const [subjectType, setSubjectType] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [sourceModule, setSourceModule] = useState("");
  const [textQuery, setTextQuery] = useState("");
  const [after, setAfter] = useState("");
  const [before, setBefore] = useState("");
  const [page, setPage] = useState(0);

  const listQuery = useMemo(
    () => ({
      action: action || undefined,
      severity: severity || undefined,
      actor: actor.trim() || undefined,
      subject_type: subjectType.trim() || undefined,
      subject_id: subjectId.trim() || undefined,
      source_module: sourceModule.trim() || undefined,
      after: fromInputValue(after),
      before: fromInputValue(before),
      text_query: textQuery.trim() || undefined,
      page: page + 1,
      page_size: PAGE_SIZE,
    }),
    [action, severity, actor, subjectType, subjectId, sourceModule, textQuery, after, before, page]
  );
  const records = useQuery({
    queryKey: auditKeys.records(listQuery),
    queryFn: () => getAuditRecords(listQuery),
  });

  const resetPage = () => setPage(0);
  const list = records.data ?? [];
  const shortPage = list.length < PAGE_SIZE;

  return (
    <div className="space-y-4">
      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Filters</h2>
        <p className="meta-text mb-3 mt-0.5">
          All filters run server-side. Text search matches description, details,
          and subject ID.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Action" id="audit-action">
            <Select id="audit-action" value={action} onChange={(e) => { setAction(e.target.value); resetPage(); }}>
              <option value="">All actions</option>
              {ACTIONS.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </Select>
          </Field>
          <Field label="Severity" id="audit-severity">
            <Select id="audit-severity" value={severity} onChange={(e) => { setSeverity(e.target.value); resetPage(); }}>
              <option value="">All severities</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
          </Field>
          <Field label="Actor" id="audit-actor">
            <Input id="audit-actor" value={actor} onChange={(e) => { setActor(e.target.value); resetPage(); }} placeholder="system" />
          </Field>
          <Field label="Source module" id="audit-module">
            <Input id="audit-module" value={sourceModule} onChange={(e) => { setSourceModule(e.target.value); resetPage(); }} placeholder="research" />
          </Field>
          <Field label="Subject type" id="audit-subject-type">
            <Input id="audit-subject-type" value={subjectType} onChange={(e) => { setSubjectType(e.target.value); resetPage(); }} placeholder="document" />
          </Field>
          <Field label="Subject ID" id="audit-subject-id">
            <Input id="audit-subject-id" value={subjectId} onChange={(e) => { setSubjectId(e.target.value); resetPage(); }} placeholder="d1" />
          </Field>
          <Field label="After" id="audit-after" hint="Event time, inclusive">
            <Input id="audit-after" type="datetime-local" value={after} onChange={(e) => { setAfter(e.target.value); resetPage(); }} />
          </Field>
          <Field label="Before" id="audit-before" hint="Event time, inclusive">
            <Input id="audit-before" type="datetime-local" value={before} onChange={(e) => { setBefore(e.target.value); resetPage(); }} />
          </Field>
        </div>
        <div className="mt-3">
          <Field label="Text search" id="audit-text" hint="Server-side: description, details, subject ID">
            <Input
              id="audit-text"
              value={textQuery}
              onChange={(e) => { setTextQuery(e.target.value); resetPage(); }}
              placeholder="e.g. kyc approval"
            />
          </Field>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Records" description="Chain order — oldest first (backend sequence order)" />
        <div className="card-body" aria-live="polite">
          {records.isPending ? (
            <Skeleton lines={5} />
          ) : records.isError ? (
            <ErrorState title="Audit records unavailable" error={records.error} onRetry={() => void records.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No audit records" description="No records match these filters. An empty result is not an integrity verdict — see the banner above." />
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <caption className="sr-only">Audit records in chain order with event, subject, severity, and actor</caption>
                  <THead>
                    <TR>
                      <TH scope="col">Seq</TH>
                      <TH scope="col">Event time</TH>
                      <TH scope="col">Action</TH>
                      <TH scope="col">Subject</TH>
                      <TH scope="col">Severity</TH>
                      <TH scope="col">Actor</TH>
                      <TH scope="col">Description</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {list.map((r) => (
                      <TR key={r.audit_id}>
                        <TD className="font-mono text-[11px]">{r.sequence}</TD>
                        <TD className="whitespace-nowrap text-[11px]">{r.timestamp ? formatRelative(r.timestamp) : "time unknown"}</TD>
                        <TD><Badge size="sm">{str(r.action) ?? "unknown"}</Badge></TD>
                        <TD className="max-w-[180px] truncate text-[11px]" title={`${r.subject_type}:${r.subject_id}`}>
                          {r.subject_type && r.subject_id ? `${r.subject_type}:${r.subject_id}` : "—"}
                        </TD>
                        <TD><Badge tone={severityTone(str(r.severity) ?? "")} size="sm">{str(r.severity) ?? "unknown"}</Badge></TD>
                        <TD className="text-[11px]">{str(r.actor) ?? "unknown"}</TD>
                        <TD className="max-w-[240px] truncate text-[11px]" title={str(r.description) ?? undefined}>
                          {str(r.description) ?? "—"}
                        </TD>
                        <TD>
                          <Button variant="ghost" size="sm" onClick={() => onSelectRecord(r.audit_id)} aria-label={`Inspect record ${r.audit_id}`}>
                            Inspect
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="meta-text">Page {page + 1} · {list.length} shown</span>
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</Button>
                  <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>Next</Button>
                </div>
              </div>
            </>
          )}
        </div>
      </Card>

      {recordId && <RecordDetail recordId={recordId} onClose={() => onSelectRecord(null)} onOpenEvidence={onOpenEvidence} />}
    </div>
  );
}

function RecordDetail({
  recordId,
  onClose,
  onOpenEvidence,
}: {
  recordId: string;
  onClose: () => void;
  onOpenEvidence: (id: string) => void;
}) {
  const detail = useQuery({
    queryKey: auditKeys.record(recordId),
    queryFn: () => getAuditRecord(recordId),
  });
  const evidence = useQuery({
    queryKey: auditKeys.evidence({ record_id: recordId }),
    queryFn: () => getAuditEvidence({ record_id: recordId }),
    enabled: detail.isSuccess,
  });

  if (detail.isPending) {
    return (
      <Card padding="md" aria-label="Record loading">
        <Skeleton className="h-6 w-1/2" />
        <div className="mt-3"><Skeleton lines={4} /></div>
      </Card>
    );
  }
  if (detail.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title="Record unavailable"
          error={detail.error}
          onRetry={() => void detail.refetch()}
          action={<Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}
        />
      </Card>
    );
  }

  const r: AuditRecord = detail.data;
  const detailFields = scalarEntries(r.details);
  const evList = evidence.data ?? [];

  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">Record {r.audit_id}</h3>
          <Badge size="sm">{str(r.action) ?? "unknown"}</Badge>
          <Badge tone={severityTone(str(r.severity) ?? "")} size="sm">{str(r.severity) ?? "unknown"}</Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>Close</Button>
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
          <div>
            <dt className="meta-text">Event time</dt>
            <dd className="text-slate-700 dark:text-slate-200">{r.timestamp ? formatRelative(r.timestamp) : "time unknown"}</dd>
          </div>
          <div>
            <dt className="meta-text">Recorded actor</dt>
            <dd className="text-slate-700 dark:text-slate-200">{str(r.actor) ?? "unknown"}{r.actor_role ? ` (${r.actor_role})` : ""}</dd>
          </div>
          <div>
            <dt className="meta-text">Subject</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {r.subject_type && r.subject_id ? `${r.subject_type}:${r.subject_id}` : "none recorded"}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Source module</dt>
            <dd className="text-slate-700 dark:text-slate-200">{str(r.source_module) ?? "none recorded"}</dd>
          </div>
          <div>
            <dt className="meta-text">Sequence</dt>
            <dd className="font-mono text-xs text-slate-600 dark:text-slate-300">{r.sequence}</dd>
          </div>
          <div>
            <dt className="meta-text">Record hash (SHA-256)</dt>
            <dd><HashValue value={str(r.record_hash) ?? ""} /></dd>
          </div>
          <div>
            <dt className="meta-text">Previous hash</dt>
            <dd><HashValue value={str(r.prev_hash) ?? ""} /></dd>
          </div>
          <div>
            <dt className="meta-text">Audit ID</dt>
            <dd className="break-all font-mono text-xs text-slate-600 dark:text-slate-300">{r.audit_id}</dd>
          </div>
        </dl>

        {str(r.description) && (
          <section aria-label="Description" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Description</h4>
            <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{r.description}</p>
          </section>
        )}

        {(str(r.ip_address) || str(r.user_agent)) && (
          <section aria-label="Request context" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Request context</h4>
            <dl className="meta-text mt-1 space-y-0.5">
              {str(r.ip_address) && <div>IP: {r.ip_address}</div>}
              {str(r.user_agent) && <div>User agent: {r.user_agent}</div>}
            </dl>
          </section>
        )}

        <section aria-label="Detail fields" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Detail fields</h4>
          {detailFields.length === 0 ? (
            <p className="meta-text mt-1">No plain-text detail fields on this record.</p>
          ) : (
            <dl className="mt-1 space-y-1 text-xs">
              {detailFields.map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="meta-text shrink-0">{k}</dt>
                  <dd className="min-w-0 break-words text-slate-700 dark:text-slate-200">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section aria-label="Associated evidence" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Associated evidence ({evidence.data ? evList.length : "…"})
          </h4>
          {evidence.isPending ? (
            <Skeleton className="mt-2 h-8" />
          ) : evidence.isError ? (
            <p className="meta-text mt-1">Evidence for this record could not be loaded.</p>
          ) : evList.length === 0 ? (
            <p className="meta-text mt-1">No evidence is associated with this record.</p>
          ) : (
            <ul className="mt-2 space-y-1">
              {evList.map((e) => (
                <li key={e.evidence_id} className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge size="sm">{str(e.kind) ?? "unknown"}</Badge>
                  <button
                    type="button"
                    onClick={() => onOpenEvidence(e.evidence_id)}
                    className="truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                    title={str(e.title) ?? e.evidence_id}
                  >
                    {str(e.title) ?? e.evidence_id}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Card>
  );
}

/* ─── evidence tab ─────────────────────────────────────────────────── */

function EvidenceTab({
  evidenceId,
  onSelectEvidence,
  onOpenRecord,
}: {
  evidenceId: string | null;
  onSelectEvidence: (id: string | null) => void;
  onOpenRecord: (id: string) => void;
}) {
  const [recordFilter, setRecordFilter] = useState("");
  const evQuery = useMemo(
    () => ({ record_id: recordFilter.trim() || undefined }),
    [recordFilter]
  );
  const evidence = useQuery({
    queryKey: auditKeys.evidence(evQuery),
    queryFn: () => getAuditEvidence(evQuery),
  });

  const list = evidence.data ?? [];

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Evidence"
          description="Items attached to audit records (server filter by record)"
          actions={
            <Input
              aria-label="Filter evidence by record ID"
              value={recordFilter}
              onChange={(e) => setRecordFilter(e.target.value)}
              placeholder="record aud-…"
              className="max-w-[220px] text-xs"
            />
          }
        />
        <div className="card-body" aria-live="polite">
          {evidence.isPending ? (
            <Skeleton lines={4} />
          ) : evidence.isError ? (
            <ErrorState title="Evidence unavailable" error={evidence.error} onRetry={() => void evidence.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No evidence" description={recordFilter ? "No evidence is attached to this record." : "No evidence has been collected yet."} />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <caption className="sr-only">Audit evidence with kind, title, associated record, and collection time</caption>
                <THead>
                  <TR>
                    <TH scope="col">Evidence ID</TH>
                    <TH scope="col">Kind</TH>
                    <TH scope="col">Title</TH>
                    <TH scope="col">Record</TH>
                    <TH scope="col">Collected</TH>
                    <TH scope="col"><span className="sr-only">Actions</span></TH>
                  </TR>
                </THead>
                <TBody>
                  {list.map((e) => (
                    <TR key={e.evidence_id}>
                      <TD className="font-mono text-[11px]" title={e.evidence_id}>{shortHash(e.evidence_id)}</TD>
                      <TD><Badge size="sm">{str(e.kind) ?? "unknown"}</Badge></TD>
                      <TD className="max-w-[220px] truncate text-[11px]" title={str(e.title) ?? undefined}>{str(e.title) ?? "Untitled evidence"}</TD>
                      <TD>
                        {str(e.record_id) ? (
                          <button
                            type="button"
                            onClick={() => onOpenRecord(e.record_id as string)}
                            className="font-mono text-[11px] text-brand-700 hover:underline dark:text-brand-300"
                            title={e.record_id as string}
                          >
                            {shortHash(e.record_id as string)}
                          </button>
                        ) : (
                          <span className="meta-text">unlinked</span>
                        )}
                      </TD>
                      <TD className="whitespace-nowrap text-[11px]">{e.collected_at ? formatRelative(e.collected_at) : "time unknown"}</TD>
                      <TD>
                        <Button variant="ghost" size="sm" onClick={() => onSelectEvidence(e.evidence_id)} aria-label={`Inspect evidence ${e.evidence_id}`}>
                          Inspect
                        </Button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </div>
      </Card>

      {evidenceId && <EvidenceDetail evidenceId={evidenceId} onClose={() => onSelectEvidence(null)} onOpenRecord={onOpenRecord} />}
    </div>
  );
}

function EvidenceDetail({
  evidenceId,
  onClose,
  onOpenRecord,
}: {
  evidenceId: string;
  onClose: () => void;
  onOpenRecord: (id: string) => void;
}) {
  const detail = useQuery({
    queryKey: auditKeys.evidenceDetail(evidenceId),
    queryFn: () => getAuditEvidenceById(evidenceId),
  });

  if (detail.isPending) {
    return (
      <Card padding="md" aria-label="Evidence loading">
        <Skeleton className="h-6 w-1/2" />
        <div className="mt-3"><Skeleton lines={3} /></div>
      </Card>
    );
  }
  if (detail.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title="Evidence unavailable"
          error={detail.error}
          onRetry={() => void detail.refetch()}
          action={<Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}
        />
      </Card>
    );
  }

  const e: AuditEvidence = detail.data;
  const contentFields = scalarEntries(e.content);

  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">{str(e.title) ?? "Untitled evidence"}</h3>
          <Badge size="sm">{str(e.kind) ?? "unknown"}</Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>Close</Button>
        </div>
        {str(e.description) && <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">{e.description}</p>}

        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
          <div>
            <dt className="meta-text">Content hash (SHA-256)</dt>
            <dd><HashValue value={str(e.content_hash) ?? ""} /></dd>
          </div>
          <div>
            <dt className="meta-text">Collected</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {e.collected_at ? formatRelative(e.collected_at) : "time unknown"}
              {str(e.collected_by) ? ` · by ${e.collected_by}` : ""}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Source</dt>
            <dd className="break-all text-slate-700 dark:text-slate-200">
              {str(e.source_uri) ? (
                /^https?:\/\//i.test(e.source_uri as string) ? (
                  <a href={e.source_uri as string} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline dark:text-brand-300">
                    {e.source_uri}
                  </a>
                ) : (
                  e.source_uri
                )
              ) : (
                "none recorded"
              )}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Evidence ID</dt>
            <dd className="break-all font-mono text-xs text-slate-600 dark:text-slate-300">{e.evidence_id}</dd>
          </div>
        </dl>

        {arr(e.tags).filter((t) => typeof t === "string").length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {arr(e.tags).filter((t): t is string => typeof t === "string").map((t) => (
              <Badge key={t}>{t}</Badge>
            ))}
          </div>
        )}

        <section aria-label="Content fields" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Content fields</h4>
          {contentFields.length === 0 ? (
            <p className="meta-text mt-1">No plain-text content fields. Content is a structured payload, not an excerpt.</p>
          ) : (
            <dl className="mt-1 space-y-1 text-xs">
              {contentFields.map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="meta-text shrink-0">{k}</dt>
                  <dd className="min-w-0 break-words text-slate-700 dark:text-slate-200">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section aria-label="Associated record" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Associated record</h4>
          {str(e.record_id) ? (
            <Button variant="ghost" size="sm" className="mt-1" onClick={() => onOpenRecord(e.record_id as string)}>
              Inspect record {shortHash(e.record_id as string)}
            </Button>
          ) : (
            <p className="meta-text mt-1">This evidence is not linked to a record.</p>
          )}
        </section>
      </div>
    </Card>
  );
}

/* ─── reports tab ──────────────────────────────────────────────────── */

const REPORT_PAGE_NOTE = "Reports are listed as stored (backend order). No export endpoint exists.";

function ReportsTab({
  onOpenRecord,
  onOpenEvidence,
}: {
  onOpenRecord: (id: string) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [kind, setKind] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [genKind, setGenKind] = useState("internal_audit");
  const [regulator, setRegulator] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [sectionTitles, setSectionTitles] = useState("");

  const listQuery = useMemo(() => ({ kind: kind || undefined }), [kind]);
  const reports = useQuery({
    queryKey: auditKeys.reports(listQuery),
    queryFn: () => getAuditReports(listQuery),
  });

  const generate = useMutation({
    mutationFn: generateAuditReport,
    onSuccess: (report) => {
      setSelectedId(report.report_id);
      void qc.invalidateQueries({ queryKey: [...auditKeys.all, "reports"] });
      setTitle("");
      setRegulator("");
      setPeriodStart("");
      setPeriodEnd("");
      setSectionTitles("");
      toast.push({ title: "Report generated", description: report.title.slice(0, 100), tone: "success" });
    },
  });

  const handleGenerate = () => {
    if (generate.isPending || title.trim().length < 3) return;
    generate.mutate({
      title: title.trim(),
      kind: genKind || undefined,
      regulator: regulator.trim() || undefined,
      period_start: fromInputValue(periodStart),
      period_end: fromInputValue(periodEnd),
      section_titles: sectionTitles.split(",").map((s) => s.trim()).filter(Boolean),
    });
  };

  const list = reports.data ?? [];
  const selected = list.find((r) => r.report_id === selectedId) ?? null;

  return (
    <div className="space-y-4">
      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Generate report</h2>
        <p className="meta-text mb-3 mt-0.5">
          Creates a compliance report from stored audit data. Sections default
          from the report kind unless titles are given.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Title" id="report-title" hint="At least 3 characters">
            <Input id="report-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Q3 access review" />
          </Field>
          <Field label="Kind" id="report-kind">
            <Select id="report-kind" value={genKind} onChange={(e) => setGenKind(e.target.value)}>
              {REPORT_KINDS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </Select>
          </Field>
          <Field label="Regulator (optional)" id="report-regulator">
            <Input id="report-regulator" value={regulator} onChange={(e) => setRegulator(e.target.value)} placeholder="RBI" />
          </Field>
          <Field label="Sections (optional)" id="report-sections" hint="Comma-separated titles">
            <Input id="report-sections" value={sectionTitles} onChange={(e) => setSectionTitles(e.target.value)} placeholder="Access, Findings" />
          </Field>
          <Field label="Period start (optional)" id="report-start">
            <Input id="report-start" type="datetime-local" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
          </Field>
          <Field label="Period end (optional)" id="report-end">
            <Input id="report-end" type="datetime-local" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3">
          <Button variant="primary" loading={generate.isPending} disabled={generate.isPending || title.trim().length < 3} onClick={handleGenerate}>
            Generate report
          </Button>
        </div>
        {generate.isPending && (
          <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
            <p className="text-sm font-medium text-brand-900 dark:text-brand-100">Generating report…</p>
          </div>
        )}
        {generate.isError && (
          <div className="mt-3">
            <ErrorState title="Report generation failed" error={generate.error} onRetry={handleGenerate} />
          </div>
        )}
      </Card>

      <Card padding="none">
        <CardHeader
          title="Reports"
          description={REPORT_PAGE_NOTE}
          actions={
            <Select aria-label="Filter reports by kind" value={kind} onChange={(e) => setKind(e.target.value)} className="text-xs">
              <option value="">All kinds</option>
              {REPORT_KINDS.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </Select>
          }
        />
        <div className="card-body" aria-live="polite">
          {reports.isPending ? (
            <Skeleton lines={3} />
          ) : reports.isError ? (
            <ErrorState title="Reports unavailable" error={reports.error} onRetry={() => void reports.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No reports" description="Generate a report above to create the first entry." />
          ) : (
            <ul className="space-y-2">
              {list.map((r) => (
                <li key={r.report_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(selectedId === r.report_id ? null : r.report_id)}
                    aria-expanded={selectedId === r.report_id}
                    className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{str(r.title) ?? "Untitled report"}</span>
                      <Badge tone={reportStatusTone(str(r.status) ?? "")} size="sm">{str(r.status) ?? "unknown"}</Badge>
                      <Badge size="sm">{str(r.kind) ?? "unknown kind"}</Badge>
                      <span className="meta-text ml-auto">{r.generated_at ? formatRelative(r.generated_at) : "time unknown"}</span>
                    </div>
                    <p className="meta-text mt-1">
                      {r.period_start || r.period_end
                        ? `${r.period_start ? formatDate(toMillis(r.period_start)) : "…"} – ${r.period_end ? formatDate(toMillis(r.period_end)) : "…"}`
                        : "no period recorded"}
                      {" · "}{arr(r.sections).length} section(s)
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {selected && (
        <ReportDetail report={selected} onClose={() => setSelectedId(null)} onOpenRecord={onOpenRecord} onOpenEvidence={onOpenEvidence} />
      )}
    </div>
  );
}

function ReportDetail({
  report: r,
  onClose,
  onOpenRecord,
  onOpenEvidence,
}: {
  report: ComplianceReport;
  onClose: () => void;
  onOpenRecord: (id: string) => void;
  onOpenEvidence: (id: string) => void;
}) {
  const sections = arr<ReportSection>(r.sections).slice().sort((a, b) => (num(a.order) ?? 0) - (num(b.order) ?? 0));
  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">{str(r.title) ?? "Untitled report"}</h3>
          <Badge tone={reportStatusTone(str(r.status) ?? "")} size="sm">{str(r.status) ?? "unknown"}</Badge>
          <Badge size="sm">{str(r.kind) ?? "unknown kind"}</Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>Close</Button>
        </div>
        {str(r.description) && <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">{r.description}</p>}

        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
          <div>
            <dt className="meta-text">Period</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {r.period_start || r.period_end
                ? `${r.period_start ? formatDate(toMillis(r.period_start)) : "…"} – ${r.period_end ? formatDate(toMillis(r.period_end)) : "…"}`
                : "no period recorded"}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Generated</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {r.generated_at ? formatRelative(r.generated_at) : "time unknown"}
              {str(r.generated_by) ? ` · by ${r.generated_by}` : ""}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Completed</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {r.completed_at ? formatRelative(r.completed_at) : "not completed"}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Regulator</dt>
            <dd className="text-slate-700 dark:text-slate-200">{str(r.regulator) ?? "none recorded"}</dd>
          </div>
        </dl>

        {str(r.attestation) && (
          <section aria-label="Attestation" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Attestation</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-200">{r.attestation}</p>
          </section>
        )}

        <section aria-label="Sections" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Sections ({sections.length})
          </h4>
          {sections.length === 0 ? (
            <p className="meta-text mt-1">This report defines no sections.</p>
          ) : (
            <div className="mt-2 space-y-3">
              {sections.map((s, i) => (
                <article key={str(s.section_id) ?? `sec-${i}`} aria-label={str(s.title) ?? `Section ${i + 1}`}>
                  <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{str(s.title) ?? "Untitled section"}</h5>
                  {str(s.summary) && <p className="mt-1 text-sm text-slate-700 dark:text-slate-200">{s.summary}</p>}
                  {arr(s.findings).filter((f) => typeof f === "string").length > 0 && (
                    <>
                      <p className="meta-text mb-1 mt-2">Findings</p>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">
                        {arr(s.findings).filter((f): f is string => typeof f === "string").map((f, j) => (
                          <li key={j}>{f}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {arr(s.recommendations).filter((x) => typeof x === "string").length > 0 && (
                    <>
                      <p className="meta-text mb-1 mt-2">Recommendations</p>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">
                        {arr(s.recommendations).filter((x): x is string => typeof x === "string").map((x, j) => (
                          <li key={j}>{x}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {arr(s.evidence_refs).filter((x) => typeof x === "string").length > 0 && (
                    <p className="meta-text mt-2">
                      Evidence:{" "}
                      {arr(s.evidence_refs).filter((x): x is string => typeof x === "string").map((id, j, all) => (
                        <span key={id}>
                          <button type="button" onClick={() => onOpenEvidence(id)} className="font-mono text-[11px] text-brand-700 hover:underline dark:text-brand-300" title={id}>
                            {shortHash(id)}
                          </button>
                          {j < all.length - 1 ? ", " : ""}
                        </span>
                      ))}
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>

        <section aria-label="Referenced records" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Referenced records ({arr(r.record_refs).filter((x) => typeof x === "string").length})
          </h4>
          {arr(r.record_refs).filter((x) => typeof x === "string").length === 0 ? (
            <p className="meta-text mt-1">No record references.</p>
          ) : (
            <ul className="mt-1 flex flex-wrap gap-1">
              {arr(r.record_refs).filter((x): x is string => typeof x === "string").map((id) => (
                <li key={id}>
                  <button type="button" onClick={() => onOpenRecord(id)} className="rounded border border-slate-200 px-2 py-0.5 font-mono text-[11px] text-brand-700 hover:underline dark:border-slate-700 dark:text-brand-300" title={id}>
                    {shortHash(id)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Card>
  );
}
