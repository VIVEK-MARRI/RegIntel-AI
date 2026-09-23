import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Input, Select, TextArea } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative } from "@/lib/format";
import { researchKeys } from "@/lib/queryKeys";
import {
  getResearchReport,
  getResearchReports,
  getResearchStats,
  runResearch,
} from "@/services/api/researchApi";
import type {
  ResearchCitation,
  ResearchKind,
  ResearchReport,
  ResearchStep,
} from "@/types/api/research";

/**
 * Research workspace: structured regulatory investigation reports.
 *
 * Backend reality (app/api/v1/research.py + app/schemas/research.py):
 * - POST /research/run is SYNCHRONOUS: it blocks until the full report is
 *   ready and returns it. There is no job queue, no task-status endpoint,
 *   no streaming, no cancellation, and no retry endpoint.
 * - Reports persist server-side: GET /research (generated_at desc, paged,
 *   optional kind filter) and GET /research/{report_id} (404 when unknown).
 * - Reports carry steps[] (per-step status), key_findings[] (STRINGS),
 *   timeline[]/comparisons[] (kind-specific dicts), citations[] — and NO
 *   confidence, NO report-level status, NO progress percent. None is shown.
 */

const KINDS: ResearchKind[] = ["general", "multi_hop", "cross_document", "timeline", "comparative"];
const KIND_LABELS: Record<ResearchKind, string> = {
  general: "General",
  multi_hop: "Multi-hop",
  cross_document: "Cross-document",
  timeline: "Timeline",
  comparative: "Comparative",
};

const PAGE_SIZE = 20;
const DEFAULT_MAX_STEPS = 8;

type StepTone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
function stepTone(s: string): StepTone {
  switch (s) {
    case "completed": return "success";
    case "running": return "info";
    case "failed": return "danger";
    default: return "neutral";
  }
}

/** Runtime guards: backend arrays are trusted but never assumed. */
function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Backend duration_ms → "4.2s" / "380ms"; null when absent so nothing is invented. */
function fmtDuration(ms: unknown): string | null {
  const n = num(ms);
  if (n === null || n <= 0) return null;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`;
}

export function ResearchPage() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const [question, setQuestion] = useState("");
  const [kind, setKind] = useState<ResearchKind>("general");
  const [maxSteps, setMaxSteps] = useState(DEFAULT_MAX_STEPS);
  const [listKind, setListKind] = useState("");
  const [page, setPage] = useState(0);

  // Deep link owns the selection: no local selected-report state exists,
  // so an unknown id can never silently render a different report.
  useEffect(() => {
    if (reportId) {
      window.scrollTo({ top: 0 });
    }
  }, [reportId]);

  const stats = useQuery({ queryKey: researchKeys.stats(), queryFn: getResearchStats });

  const listQuery = useMemo(
    () => ({
      kind: (listKind || undefined) as ResearchKind | undefined,
      page: page + 1,
      page_size: PAGE_SIZE,
    }),
    [listKind, page]
  );
  const reports = useQuery({
    queryKey: researchKeys.reports(listQuery),
    queryFn: () => getResearchReports(listQuery),
  });

  const run = useMutation({
    mutationFn: runResearch,
    onSuccess: (report) => {
      // Seed the detail cache with the authoritative response, refresh the
      // list prefix, then navigate to the REAL report route.
      qc.setQueryData(researchKeys.report(report.report_id), report);
      void qc.invalidateQueries({ queryKey: [...researchKeys.all, "reports"] });
      setQuestion("");
      toast.push({
        title: "Research report ready",
        description: (report.query || "").slice(0, 100),
        tone: "success",
      });
      navigate(`/research/${report.report_id}`);
    },
  });

  const questionValid = question.trim().length >= 3;
  const shortPage = (reports.data?.length ?? PAGE_SIZE) < PAGE_SIZE;

  const runAgain = (q: string) => {
    setQuestion(q);
    navigate("/research");
    // Focus stays predictable after the route change.
    window.setTimeout(() => document.getElementById("research-question")?.focus(), 50);
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Research</h1>
        <p className="page-description">
          Investigate regulatory questions and produce structured, evidence-backed reports.
        </p>
      </header>

      {/* overview — aggregates from /stats only */}
      <section aria-label="Overview" className="mb-6 mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : stats.isError ? (
          <div className="sm:col-span-3">
            <ErrorState
              title="Research statistics unavailable"
              error={stats.error}
              onRetry={() => {
                void stats.refetch();
              }}
            />
          </div>
        ) : (
          <>
            <Metric
              label="Stored reports"
              value={stats.data.total_reports.toLocaleString()}
              hint="Newest first in the list below"
            />
            <Metric
              label="Steps executed"
              value={stats.data.steps_total.toLocaleString()}
              hint={`Across ${stats.data.plans_generated.toLocaleString()} plan(s)`}
            />
            <Metric
              label="Last report"
              value={stats.data.last_report_at ? formatRelative(stats.data.last_report_at) : "—"}
              hint="Most recent generation time"
            />
          </>
        )}
      </section>

      {/* request — only controls the backend request schema actually supports */}
      <Card padding="md" className="mb-4">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">New research</h2>
        <p className="meta-text mb-3 mt-0.5">
          Runs synchronously: the request stays open until the report is ready. Larger step
          budgets take longer.
        </p>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_180px_140px_auto]">
          <Field label="Research question" id="research-question" hint="At least 3 characters">
            <TextArea
              id="research-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How did KYC periodic updation rules change in 2024?"
              rows={2}
            />
          </Field>
          <Field label="Kind" id="research-kind">
            <Select
              id="research-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as ResearchKind)}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>{KIND_LABELS[k]}</option>
              ))}
            </Select>
          </Field>
          <Field label="Max steps" id="research-steps" hint="1–20">
            <Input
              id="research-steps"
              type="number"
              min={1}
              max={20}
              value={maxSteps}
              onChange={(e) =>
                setMaxSteps(Math.min(20, Math.max(1, Number(e.target.value) || DEFAULT_MAX_STEPS)))
              }
            />
          </Field>
          <div className="flex items-end">
            <Button
              variant="primary"
              loading={run.isPending}
              disabled={!questionValid || run.isPending}
              onClick={() => {
                if (!questionValid || run.isPending) return;
                run.mutate({ query: question.trim(), kind, max_steps: maxSteps });
              }}
            >
              Run research
            </Button>
          </div>
        </div>
        {run.isPending && (
          <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
            <p className="text-sm font-medium text-brand-900 dark:text-brand-100">Research is running…</p>
            <p className="mt-1 text-xs text-brand-800/80 dark:text-brand-200/80">
              The workflow plans the question, runs retrieval, and generates the report in one
              request. Please wait — navigating away is safe, the report is stored when done.
            </p>
          </div>
        )}
        {run.isError && (
          <div className="mt-3">
            <ErrorState
              title="Research run failed"
              error={run.error}
              onRetry={() => {
                if (!questionValid || run.isPending) return;
                run.mutate({ query: question.trim(), kind, max_steps: maxSteps });
              }}
            />
          </div>
        )}
      </Card>

      {reportId ? (
        <ReportDetail
          reportId={reportId}
          onBack={() => navigate("/research")}
          onRunAgain={runAgain}
        />
      ) : (
        <Card padding="none">
          <CardHeader
            title="Reports"
            description="Stored research reports, newest first"
            actions={
              <select
                aria-label="Filter reports by kind"
                value={listKind}
                onChange={(e) => {
                  setListKind(e.target.value);
                  setPage(0);
                }}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-surface-dark-2 dark:text-slate-200"
              >
                <option value="">All kinds</option>
                {KINDS.map((k) => (
                  <option key={k} value={k}>{KIND_LABELS[k]}</option>
                ))}
              </select>
            }
          />
          <div className="card-body" aria-live="polite">
            {reports.isPending ? (
              <Skeleton lines={4} />
            ) : reports.isError ? (
              <ErrorState
                title="Reports unavailable"
                error={reports.error}
                onRetry={() => {
                  void reports.refetch();
                }}
              />
            ) : (reports.data ?? []).length === 0 ? (
              <EmptyState
                title="No reports yet"
                description={
                  listKind
                    ? "No stored reports of this kind. Try another kind or run a new research task."
                    : "Run a research question above to generate your first report."
                }
              />
            ) : (
              <>
                <ul className="space-y-2">
                  {(reports.data ?? []).map((r) => {
                    const steps = arr(r.steps);
                    const findings = arr<string>(r.key_findings);
                    const citations = arr(r.citations);
                    return (
                      <li key={r.report_id}>
                        <button
                          type="button"
                          onClick={() => navigate(`/research/${r.report_id}`)}
                          className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 hover:shadow-glow dark:border-slate-800 dark:hover:border-brand-500"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone="brand" size="sm">{r.kind}</Badge>
                            <span className="meta-text ml-auto">
                              {r.generated_at ? formatRelative(r.generated_at) : "time unknown"}
                            </span>
                          </div>
                          <p className="mt-2 truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                            {r.query || "Untitled research"}
                          </p>
                          <p className="meta-text mt-1">
                            {steps.length} step(s) · {findings.length} finding(s) · {citations.length} citation(s)
                          </p>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <span className="meta-text">Page {page + 1} · {(reports.data ?? []).length} shown</span>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                      Prev
                    </Button>
                    <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>
                      Next
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

function ReportDetail({
  reportId,
  onBack,
  onRunAgain,
}: {
  reportId: string;
  onBack: () => void;
  onRunAgain: (question: string) => void;
}) {
  const detail = useQuery({
    queryKey: researchKeys.report(reportId),
    queryFn: () => getResearchReport(reportId),
  });

  if (detail.isPending) {
    return (
      <Card padding="md" aria-label="Report loading">
        <Skeleton className="h-7 w-2/3" />
        <div className="mt-3">
          <Skeleton lines={4} />
        </div>
      </Card>
    );
  }

  if (detail.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title="Report unavailable"
          error={detail.error}
          onRetry={() => {
            void detail.refetch();
          }}
          action={
            <Button variant="ghost" size="sm" onClick={onBack}>
              Back to reports
            </Button>
          }
        />
      </Card>
    );
  }

  const r: ResearchReport = detail.data;
  const steps = arr<ResearchStep>(r.steps);
  const findings = arr<string>(r.key_findings).filter((f) => typeof f === "string");
  const citations = arr<ResearchCitation>(r.citations);
  const timeline = arr<Record<string, unknown>>(r.timeline);
  const comparisons = arr<Record<string, unknown>>(r.comparisons);
  const duration = fmtDuration(r.duration_ms);

  return (
    <article aria-labelledby="report-title">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to reports
        </Button>
        <Button variant="secondary" size="sm" onClick={() => onRunAgain(r.query)}>
          Run again with this question
        </Button>
      </div>

      <Card padding="none">
        <div className="card-body">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="brand" size="sm">{r.kind}</Badge>
            {duration && <span className="meta-text">Completed in {duration}</span>}
            <span className="meta-text ml-auto">{r.generated_at ? formatRelative(r.generated_at) : "time unknown"}</span>
          </div>
          <h2 id="report-title" className="mt-2 text-lg font-bold text-slate-900 dark:text-white">
            {r.query || "Untitled research"}
          </h2>
          <p className="meta-text mt-1">Report ID <span className="font-mono">{r.report_id}</span></p>

          {str(r.summary) && (
            <section aria-label="Summary" className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Summary</h3>
              <p className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm leading-relaxed text-slate-700 dark:bg-slate-800/40 dark:text-slate-200">
                {r.summary}
              </p>
            </section>
          )}

          <section aria-label="Steps" className="mt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Steps ({steps.length})</h3>
            {steps.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No steps recorded for this report.</p>
            ) : (
              <ol className="mt-2 space-y-1.5">
                {steps.map((s, i) => {
                  const d = fmtDuration(s.duration_ms);
                  return (
                    <li
                      key={str(s.step_id) ?? `step-${i}`}
                      className="flex items-start gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
                    >
                      <span aria-hidden className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-slate-900 dark:text-slate-100">
                          {str(s.description) ?? "Unnamed step"}
                        </p>
                        <p className="meta-text mt-0.5">
                          {str(s.step_type) ?? "step"}
                          {d ? ` · took ${d}` : ""}
                        </p>
                        {s.status === "failed" && str(s.error) && (
                          <p className="mt-1 text-xs text-red-700 dark:text-red-300">{s.error}</p>
                        )}
                      </div>
                      <Badge tone={stepTone(str(s.status) ?? "")} size="sm">
                        {str(s.status) ?? "unknown"}
                      </Badge>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <section aria-label="Key findings" className="mt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Key findings ({findings.length})</h3>
            {findings.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                This report contains no findings — distinct from a failed run (steps above show what executed).
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {findings.map((f, i) => (
                  <li key={i} className="rounded-xl border border-slate-200 p-3 text-sm leading-relaxed text-slate-700 dark:border-slate-800 dark:text-slate-200">
                    {f}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {timeline.length > 0 && (
            <section aria-label="Timeline" className="mt-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Timeline ({timeline.length})</h3>
              <ul className="mt-2 space-y-1.5">
                {timeline.map((t, i) => (
                  <li key={i} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{str(t.title) ?? "Untitled event"}</p>
                    <p className="meta-text mt-0.5">
                      {[str(t.date) ?? (num(t.date) ? formatRelative(t.date as number) : null), str(t.id) ?? (num(t.id) ? String(t.id) : null)]
                        .filter(Boolean)
                        .join(" · ") || "no date recorded"}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {comparisons.length > 0 && (
            <section aria-label="Comparisons" className="mt-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Comparisons ({comparisons.length})</h3>
              <ul className="mt-2 space-y-1.5">
                {comparisons.map((c, i) => (
                  <li key={i} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <p className="font-medium text-slate-900 dark:text-slate-100">{str(c.step) ?? "Comparison"}</p>
                    {num(c.items_compared) !== null && (
                      <p className="meta-text mt-0.5">{c.items_compared as number} item(s) compared</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-label="Citations" className="mt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Sources & citations ({citations.length})</h3>
            {citations.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                No citations in this report. Findings above stand on their own text — no sources are implied.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {citations.map((c, i) => (
                  <li key={str(c.citation_id) ?? `cit-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge size="sm">{str(c.source) ?? "unknown source"}</Badge>
                      {str(c.url) && (
                        <a
                          href={c.url as string}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`Open reference: ${str(c.title) ?? "source"}`}
                          className="ml-auto text-brand-700 hover:underline dark:text-brand-300"
                        >
                          Open reference
                        </a>
                      )}
                    </div>
                    <p className="mt-1 truncate font-medium text-slate-900 dark:text-slate-100">
                      {str(c.title) ?? "Untitled source"}
                    </p>
                    {str(c.reference) && (
                      <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{c.reference}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </Card>
    </article>
  );
}
