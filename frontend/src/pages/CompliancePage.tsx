import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useComplianceAssessments, useRunCompliance } from "@/hooks/api";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative } from "@/lib/format";
import type { ComplianceAssessment } from "@/types";

export function CompliancePage() {
  const assessments = useComplianceAssessments();
  const run = useRunCompliance();
  const toast = useToast();
  const [scope, setScope] = useState("All regulated entities");
  const [policies, setPolicies] = useState("kyc,aml,outsourcing,data-localisation");
  const [selected, setSelected] = useState<ComplianceAssessment | null>(null);

  async function handleRun() {
    if (!scope.trim()) return;
    try {
      const result = await run.mutateAsync({
        scope,
        policies: policies.split(",").map((p) => p.trim()).filter(Boolean),
      });
      setSelected(result);
      toast.push({
        title: "Assessment complete",
        description: `Risk level: ${result.risk_level}`,
        tone: "success",
      });
    } catch (err) {
      toast.push({
        title: "Compliance run failed",
        description: err instanceof Error ? err.message : "Unexpected error",
        tone: "danger",
      });
    }
  }

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        <Card padding="md">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Compliance Workspace
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Assess obligations, identify gaps, and generate remediation actions.
          </p>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Scope" id="compliance-scope">
              <Input
                id="compliance-scope"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                placeholder="e.g. NBFC, Trading desk"
              />
            </Field>
            <Field label="Policies (comma-separated)" id="compliance-policies">
              <Input
                id="compliance-policies"
                value={policies}
                onChange={(e) => setPolicies(e.target.value)}
                placeholder="kyc, aml, ..."
              />
            </Field>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              onClick={handleRun}
              loading={run.isPending}
              disabled={!scope.trim()}
            >
              Run assessment
            </Button>
          </div>
        </Card>

        {selected ? (
          <AssessmentDetail assessment={selected} />
        ) : (
          <Card padding="none">
            <CardHeader
              title="Recent assessments"
              description="Stored compliance assessments"
            />
            <div className="card-body">
              {assessments.isLoading ? (
                <Skeleton lines={4} />
              ) : assessments.isError ? (
                <ErrorState error={assessments.error} onRetry={() => assessments.refetch()} />
              ) : !assessments.data || assessments.data.length === 0 ? (
                <EmptyState
                  title="No assessments yet"
                  description="Run an assessment above to view obligations and gaps."
                />
              ) : (
                <ul className="space-y-2">
                  {assessments.data.map((a) => (
                    <li
                      key={a.assessment_id}
                      className="cursor-pointer rounded-xl border border-slate-200 p-3 transition hover:border-brand-300 hover:shadow-glow dark:border-slate-800 dark:hover:border-brand-500"
                      onClick={() => setSelected(a)}
                    >
                      <div className="flex items-center gap-2">
                        <Badge
                          tone={
                            a.risk_level === "critical"
                              ? "danger"
                              : a.risk_level === "high"
                                ? "warning"
                                : a.risk_level === "medium"
                                  ? "info"
                                  : "success"
                          }
                        >
                          {a.risk_level}
                        </Badge>
                        <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {a.scope}
                        </span>
                        <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                          {formatRelative(a.generated_at)}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                        <div>
                          <p className="text-slate-500 dark:text-slate-400">Score</p>
                          <p className="font-semibold">{a.overall_score}/100</p>
                        </div>
                        <div>
                          <p className="text-slate-500 dark:text-slate-400">Obligations</p>
                          <p className="font-semibold">{a.obligations.length}</p>
                        </div>
                        <div>
                          <p className="text-slate-500 dark:text-slate-400">Gaps</p>
                          <p className="font-semibold">{a.gaps.length}</p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>
        )}
      </div>

      <aside className="space-y-4">
        <Card padding="md">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Severity distribution
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Aggregated across the latest assessment.
          </p>
          <div className="mt-3 space-y-2">
            {(
              ["critical", "high", "medium", "low"] as const
            ).map((sev) => {
              const count = selected
                ? selected.gaps.filter((g) => g.severity === sev).length
                : 0;
              return (
                <div key={sev} className="text-xs">
                  <div className="flex items-center justify-between">
                    <span className="capitalize text-slate-700 dark:text-slate-200">
                      {sev}
                    </span>
                    <span className="font-mono text-slate-500 dark:text-slate-400">
                      {count}
                    </span>
                  </div>
                  <ProgressBar
                    value={count}
                    max={Math.max(1, selected?.gaps.length ?? 1)}
                    tone={
                      sev === "critical"
                        ? "danger"
                        : sev === "high"
                          ? "warning"
                          : "brand"
                    }
                    className="mt-1"
                  />
                </div>
              );
            })}
          </div>
        </Card>
      </aside>
    </div>
  );
}

function AssessmentDetail({ assessment }: { assessment: ComplianceAssessment }) {
  return (
    <Card padding="none">
      <CardHeader
        title={assessment.scope}
        description="Detailed compliance assessment"
        actions={
          <Badge
            tone={
              assessment.risk_level === "critical"
                ? "danger"
                : assessment.risk_level === "high"
                  ? "warning"
                  : "success"
            }
          >
            {assessment.risk_level}
          </Badge>
        }
      />
      <div className="card-body space-y-5">
        <section className="grid grid-cols-3 gap-3">
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Overall score
            </p>
            <p className="mt-1 text-2xl font-semibold">{assessment.overall_score}/100</p>
          </div>
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Obligations
            </p>
            <p className="mt-1 text-2xl font-semibold">{assessment.obligations.length}</p>
          </div>
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/40">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Gaps
            </p>
            <p className="mt-1 text-2xl font-semibold">{assessment.gaps.length}</p>
          </div>
        </section>

        {assessment.obligations.length ? (
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Obligations
            </h4>
            <ul className="mt-2 space-y-2">
              {assessment.obligations.map((o) => (
                <li
                  key={o.obligation_id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      tone={
                        o.severity === "critical"
                          ? "danger"
                          : o.severity === "high"
                            ? "warning"
                            : "info"
                      }
                      size="sm"
                    >
                      {o.severity}
                    </Badge>
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {o.title}
                    </span>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {o.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                    {o.description}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {assessment.gaps.length ? (
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Identified gaps
            </h4>
            <ul className="mt-2 space-y-2">
              {assessment.gaps.map((g) => (
                <li
                  key={g.gap_id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      tone={
                        g.severity === "critical"
                          ? "danger"
                          : g.severity === "high"
                            ? "warning"
                            : "info"
                      }
                      size="sm"
                    >
                      {g.severity}
                    </Badge>
                    <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      {g.description}
                    </span>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {formatRelative(g.detected_at)}
                    </span>
                  </div>
                  {g.recommended_actions.length ? (
                    <ul className="mt-2 list-inside list-disc text-[11px] text-slate-600 dark:text-slate-300">
                      {g.recommended_actions.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </Card>
  );
}
