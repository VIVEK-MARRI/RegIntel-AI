import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getComplianceAssessments, runCompliance } from "@/services/api/complianceApi";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative } from "@/lib/format";
import type { ComplianceAssessment } from "@/types";

export function CompliancePage() {
  const { data: assessments, isLoading, isError, refetch } = useQuery({
    queryKey: ["compliance", "assessments"],
    queryFn: getComplianceAssessments,
  });
  const run = useMutation({
    mutationFn: runCompliance,
    onSuccess: () => refetch(),
  });
  const toast = useToast();
  const [scope, setScope] = useState("");
  const [policiesStr, setPoliciesStr] = useState("");
  const [selected, setSelected] = useState<ComplianceAssessment | null>(null);

  const avgScore = assessments?.length
    ? Math.round(assessments.reduce((s, a) => s + a.overall_score, 0) / assessments.length * 100)
    : null;

  async function handleRun() {
    if (!scope.trim()) return;
    const policies = policiesStr.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const result = await run.mutateAsync({ scope, policies: policies.length ? policies : undefined });
      setSelected(result);
      toast.push({ title: "Assessment complete", description: `${result.scope} — score ${Math.round(result.overall_score * 100)}%`, tone: "success" });
    } catch (err) {
      toast.push({ title: "Assessment failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  const riskTone = (level: string) => level === "critical" ? "danger" : level === "high" ? "warning" : level === "medium" ? "info" : "success";

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Compliance</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Compliance monitoring, obligations, impact analysis, and risk indicators.</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Metric label="Compliance Score" value={avgScore !== null ? `${avgScore}%` : "—"} hint={assessments ? `${assessments.length} assessment(s)` : "Loading…"} />
        <Metric label="Assessments" value={assessments?.length ?? "—"} />
        <Metric label="Open Gaps" value={assessments?.reduce((s, a) => s + a.gaps.length, 0) ?? "—"} />
      </section>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Run Compliance Assessment</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="Scope" id="compliance-scope">
            <Input id="compliance-scope" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="e.g. All regulated entities" />
          </Field>
          <Field label="Policies (comma-separated)" id="compliance-policies">
            <Input id="compliance-policies" value={policiesStr} onChange={(e) => setPoliciesStr(e.target.value)} placeholder="kyc, aml, data-localisation" />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={handleRun} loading={run.isPending} disabled={!scope.trim()}>Assess</Button>
          </div>
        </div>
      </Card>

      {selected ? <AssessmentDetail assessment={selected} /> : null}

      <Card padding="none">
        <CardHeader title="Recent Assessments" />
        <div className="card-body">
          {isLoading ? <Skeleton lines={4} />
          : isError ? <ErrorState onRetry={refetch} />
          : !assessments?.length ? <EmptyState title="No assessments yet" description="Run an assessment above." />
          : <ul className="space-y-2">
              {assessments.map((a) => (
                <li key={a.assessment_id} className="cursor-pointer rounded-xl border border-slate-200 p-3 transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                  onClick={() => setSelected(a)}>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.scope}</span>
                    <Badge tone={riskTone(a.risk_level)}>{a.risk_level}</Badge>
                    <Badge tone="brand" size="sm">{Math.round(a.overall_score * 100)}%</Badge>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">{formatRelative(a.generated_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{a.obligations.length} obligations · {a.gaps.length} gaps</p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}

function AssessmentDetail({ assessment }: { assessment: ComplianceAssessment }) {
  return (
    <Card padding="none">
      <CardHeader title={assessment.scope}
        actions={<Badge tone={assessment.risk_level === "critical" ? "danger" : assessment.risk_level === "high" ? "warning" : "info"}>{assessment.risk_level}</Badge>}
      />
      <div className="card-body space-y-4">
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Obligations ({assessment.obligations.length})</h4>
          <ul className="mt-2 space-y-1.5">
            {assessment.obligations.map((o) => (
              <li key={o.obligation_id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                <span className="flex-1 font-medium text-slate-900 dark:text-slate-100">{o.title}</span>
                <Badge tone={o.severity === "critical" ? "danger" : o.severity === "high" ? "warning" : "info"} size="sm">{o.severity}</Badge>
                <Badge tone={o.status === "met" ? "success" : o.status === "breached" ? "danger" : "warning"} size="sm">{o.status}</Badge>
              </li>
            ))}
          </ul>
        </section>
        {assessment.gaps.length ? (<section>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Gaps ({assessment.gaps.length})</h4>
          <ul className="mt-2 space-y-1.5">
            {assessment.gaps.map((g) => (
              <li key={g.gap_id} className="rounded-lg border border-red-200 bg-red-50/40 px-3 py-2 text-xs dark:border-red-900/40 dark:bg-red-950/20">
                <p className="font-medium text-red-800 dark:text-red-200">{g.description}</p>
                <p className="mt-1 text-red-600 dark:text-red-400">Actions: {g.recommended_actions.join(", ")}</p>
              </li>
            ))}
          </ul>
        </section>) : null}
      </div>
    </Card>
  );
}
