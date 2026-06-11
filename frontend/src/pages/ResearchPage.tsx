import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, TextArea } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getResearchReports, runResearch } from "@/services/api/researchApi";
import { useToast } from "@/providers/ToastProvider";
import { formatPercent, formatRelative } from "@/lib/format";
import type { ResearchReport } from "@/types";

export function ResearchPage() {
  const { data: reports, isLoading, isError, refetch } = useQuery({
    queryKey: ["research", "reports"],
    queryFn: getResearchReports,
  });
  const run = useMutation({
    mutationFn: runResearch,
    onSuccess: () => refetch(),
  });
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [depth, setDepth] = useState(2);
  const [selected, setSelected] = useState<ResearchReport | null>(null);

  async function handleRun() {
    if (!query.trim()) return;
    try {
      const result = await run.mutateAsync({ query, depth });
      setSelected(result);
      toast.push({ title: "Research report ready", description: (result.query || result.summary || "").slice(0, 80), tone: "success" });
    } catch (err) {
      toast.push({ title: "Research failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        <Card padding="md">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Research</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Run deep, multi-step regulatory research with a structured plan and grounded findings.</p>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_120px_auto]">
            <Field label="Research question" id="research-query">
              <TextArea id="research-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Compare FEMA vs RBI reporting thresholds for FY26" rows={2} />
            </Field>
            <Field label="Depth" id="research-depth">
              <Input id="research-depth" type="number" min={1} max={5} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
            </Field>
            <div className="flex items-end">
              <Button variant="primary" onClick={handleRun} loading={run.isPending} disabled={!query.trim()}>Run research</Button>
            </div>
          </div>
        </Card>

        {run.isPending ? <Card padding="md"><Skeleton lines={4} /></Card> : null}

        {selected ? <ReportDetail report={selected} />
        : <Card padding="none">
            <CardHeader title="Recent reports" description="Stored research artefacts" />
            <div className="card-body">
              {isLoading ? <Skeleton lines={4} />
              : isError ? <ErrorState onRetry={refetch} />
              : !reports?.length ? <EmptyState title="No reports yet" description="Run a research query above to generate your first report." />
              : <ul className="space-y-2">
                  {reports.map((r) => (
                    <li key={r.report_id} className="cursor-pointer rounded-xl border border-slate-200 p-3 transition hover:border-brand-300 hover:shadow-glow dark:border-slate-800 dark:hover:border-brand-500"
                      onClick={() => setSelected(r)}>
                      <div className="flex items-center gap-2">
                        <Badge tone="brand" size="sm">{r.plan?.length ?? 0} steps</Badge>
                        <Badge tone="info" size="sm">{r.findings?.length ?? 0} findings</Badge>
                        <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">{formatRelative(r.created_at)}</span>
                      </div>
                      <p className="mt-2 text-sm font-medium text-slate-900 dark:text-slate-100">{r.summary || r.query}</p>
                      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">Confidence {formatPercent(r.confidence)}</p>
                    </li>
                  ))}
                </ul>
              }
            </div>
          </Card>
        }
      </div>

      <aside className="space-y-4">
        <Card padding="md">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Workflow</h3>
          <ol className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
            <li>1. Decompose the question into a research plan.</li>
            <li>2. Search regulatory corpora and knowledge graph.</li>
            <li>3. Synthesise grounded findings with citations.</li>
            <li>4. Generate a summary, confidence, and action list.</li>
          </ol>
        </Card>
        <Card padding="md">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Best practices</h3>
          <ul className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
            <li>• Be specific about the regulatory scope.</li>
            <li>• Use depth ≥ 3 for cross-jurisdictional questions.</li>
            <li>• Always review the citations before publishing.</li>
          </ul>
        </Card>
      </aside>
    </div>
  );
}

function ReportDetail({ report }: { report: ResearchReport }) {
  return (
    <Card padding="none">
      <CardHeader title="Research report" description={report.query}
        actions={<Badge tone="success">Confidence {formatPercent(report.confidence)}</Badge>}
      />
      <div className="card-body space-y-5">
        {report.plan?.length ? (<section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Plan</h4>
          <ol className="mt-2 space-y-1.5">
            {report.plan.map((step, i) => (
              <li key={step.step_id ?? `${i}`} className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-slate-900 dark:text-slate-100">{step.description}</p>
                  <p className="truncate text-[10px] text-slate-500 dark:text-slate-400">Tools: {step.tools?.join(", ")}</p>
                </div>
                <Badge tone={step.status === "done" ? "success" : step.status === "running" ? "info" : step.status === "failed" ? "danger" : "neutral"} size="sm">{step.status}</Badge>
              </li>
            ))}
          </ol>
        </section>) : null}

        {report.findings?.length ? (<section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Findings</h4>
          <ul className="mt-2 space-y-2">
            {report.findings.map((f, i) => (
              <li key={f.finding_id ?? `${i}`} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-center gap-2">
                  <p className="flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{f.title}</p>
                  <Badge tone="brand" size="sm">{formatPercent(f.confidence)}</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{f.content}</p>
              </li>
            ))}
          </ul>
        </section>) : null}

        {report.summary ? (<section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Summary</h4>
          <p className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm text-slate-700 dark:bg-slate-800/40 dark:text-slate-200">{report.summary}</p>
        </section>) : null}
      </div>
    </Card>
  );
}
