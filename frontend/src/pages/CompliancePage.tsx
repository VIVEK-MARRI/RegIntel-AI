import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getComplianceAssessments, runCompliance } from "@/services/api/complianceApi";
import { getRiskForecasts, getRiskScenarios, forecastRisk } from "@/services/api/riskApi";
import { getPolicies, getDecisions, getGovernanceStats } from "@/services/api/governanceApi";
import { useToast } from "@/providers/ToastProvider";
import { formatNumber, formatRelative } from "@/lib/format";
import { complianceKeys, governanceKeys, riskKeys } from "@/lib/queryKeys";
import { toDecisionView, toPolicyView } from "@/adapters/governance";
import type { RiskAssessment } from "@/types/api/compliance";

export function CompliancePage() {
  const [tab, setTab] = useState<"overview" | "risk" | "governance" | "impact">("overview");

  const tabs = [
    { id: "overview" as const, label: "Overview" },
    { id: "risk" as const, label: "Risk Analysis" },
    { id: "governance" as const, label: "Governance Reviews" },
    { id: "impact" as const, label: "Impact Assessments" },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Compliance</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Compliance monitoring, risk analysis, governance reviews, and impact assessments.</p>
      </header>

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-xs font-medium transition border-b-2 -mb-px ${
              tab === t.id
                ? "border-brand-500 text-brand-700 dark:text-brand-300"
                : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab />}
      {tab === "risk" && <RiskTab />}
      {tab === "governance" && <GovernanceTab />}
      {tab === "impact" && <ImpactTab />}
    </div>
  );
}

function OverviewTab() {
  const { data: assessments, isLoading, isError, refetch } = useQuery({
    queryKey: complianceKeys.assessments(), queryFn: getComplianceAssessments,
  });
  const run = useMutation({ mutationFn: runCompliance, onSuccess: () => refetch() });
  const toast = useToast();
  const [scope, setScope] = useState("");
  const [policiesStr, setPoliciesStr] = useState("");
  const [selected, setSelected] = useState<RiskAssessment | null>(null);

  const avgScore = assessments?.length
    ? Math.round(assessments.reduce((s, a) => s + a.risk_score, 0) / assessments.length * 100)
    : null;

  const riskTone = (level: string) => level === "critical" ? "danger" : level === "high" ? "warning" : level === "medium" ? "info" : "success";

  async function handleRun() {
    if (!scope.trim()) return;
    const policies = policiesStr.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      // Backend RiskAssessmentRequest accepts document_id/diff_id/
      // impact_report_id/source/context only — scope+policies travel as
      // opaque context so the call validates (422 otherwise).
      const result = await run.mutateAsync({ source: "manual", context: { scope, policies } });
      setSelected(result);
      toast.push({ title: "Assessment complete", description: `${result.assessment_id} — risk ${Math.round(result.risk_score * 100)}%`, tone: "success" });
    } catch (err) {
      toast.push({ title: "Assessment failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Metric label="Avg Risk Score" value={avgScore !== null ? `${avgScore}%` : "—"} hint={assessments ? `${assessments.length} assessment(s)` : "Loading…"} />
        <Metric label="Assessments" value={assessments?.length ?? "—"} />
        <Metric label="Open Gaps" value={assessments?.reduce((s, a) => s + (a.compliance_gaps?.length ?? 0), 0) ?? "—"} />
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

      {selected ? (
        <Card padding="none">
          <CardHeader title={selected.document_id ?? selected.assessment_id} actions={<Badge tone={riskTone(selected.risk_level)}>{selected.risk_level}</Badge>} />
          <div className="card-body space-y-4">
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Recommended actions ({(selected.recommended_actions ?? []).length})</h4>
              <ul className="mt-2 space-y-1.5">
                {(selected.recommended_actions ?? []).map((o) => (
                  <li key={o.action_id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <span className="flex-1 font-medium text-slate-900 dark:text-slate-100">{o.title ?? "—"}</span>
                    <Badge tone="info" size="sm">{o.action_type}</Badge>
                  </li>
                ))}
              </ul>
            </section>
            {(selected.compliance_gaps ?? []).length ? (
              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Gaps ({(selected.compliance_gaps ?? []).length})</h4>
                <ul className="mt-2 space-y-1.5">
                  {(selected.compliance_gaps ?? []).map((g) => (
                    <li key={g.gap_id} className="rounded-lg border border-red-200 bg-red-50/40 px-3 py-2 text-xs dark:border-red-900/40 dark:bg-red-950/20">
                      <p className="font-medium text-red-800 dark:text-red-200">{g.description}</p>
                      <p className="mt-1 text-red-600 dark:text-red-400">{g.area} · {g.severity}</p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        </Card>
      ) : null}

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
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.document_id ?? a.assessment_id}</span>
                    <Badge tone={riskTone(a.risk_level)}>{a.risk_level}</Badge>
                    <Badge tone="brand" size="sm">{Math.round(a.risk_score * 100)}%</Badge>
                    <span className="ml-auto text-[10px] text-slate-500">{formatRelative(a.generated_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{(a.recommended_actions?.length ?? 0)} actions · {(a.compliance_gaps?.length ?? 0)} gaps</p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}

function RiskTab() {
  const { data: forecasts, isLoading: fLoading, isError: fError, refetch: fRefetch } = useQuery({
    queryKey: riskKeys.forecasts(), queryFn: getRiskForecasts,
  });
  const { data: scenarios, isLoading: sLoading, isError: sError } = useQuery({
    queryKey: riskKeys.scenarios(), queryFn: getRiskScenarios,
  });
  const run = useMutation({ mutationFn: forecastRisk });
  const toast = useToast();
  const [horizon, setHorizon] = useState(30);

  async function handleForecast() {
    try {
      const result = await run.mutateAsync({ horizon_days: horizon });
      toast.push({ title: "Forecast generated", description: `${result.horizon_days}-day: ${(result.predicted_risk_score * 100).toFixed(1)}% risk`, tone: "success" });
    } catch (err) {
      toast.push({ title: "Forecast failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  const scoreTone = (score: number) => score > 75 ? "danger" : score > 50 ? "warning" : "success";

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Metric label="Active Forecasts" value={forecasts?.length ?? "—"} />
        <Metric label="Avg Predicted Score" value={forecasts?.length ? `${Math.round(forecasts.reduce((s, f) => s + f.predicted_risk_score, 0) / forecasts.length * 100)}` : "—"} />
        <Metric label="Scenarios" value={scenarios?.length ?? "—"} />
        <Metric label="Avg Confidence" value={forecasts?.length ? `${Math.round(forecasts.reduce((s, f) => s + f.confidence, 0) / forecasts.length * 100)}%` : "—"} />
      </section>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Generate Risk Forecast</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[120px_auto]">
          <Field label="Horizon (days)" id="risk-horizon">
            <Input id="risk-horizon" type="number" min={1} max={365} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" onClick={handleForecast} loading={run.isPending}>Forecast</Button>
          </div>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Forecasts" />
        <div className="card-body">
          {fLoading ? <Skeleton lines={4} />
          : fError ? <ErrorState onRetry={fRefetch} />
          : !forecasts?.length ? <EmptyState title="No forecasts yet" description="Generate a forecast above." />
          : <ul className="space-y-3">
              {forecasts.map((f) => (
                <li key={f.forecast_id} className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-slate-700 dark:text-slate-200">{f.horizon_days}-day horizon</span>
                      <span className="text-slate-500">{formatNumber(f.predicted_risk_score * 100)} / 100</span>
                    </div>
                    <ProgressBar value={f.predicted_risk_score * 100} max={100} tone={scoreTone(f.predicted_risk_score * 100)} className="mt-1.5" />
                  </div>
                  <Badge tone={f.confidence > 0.75 ? "success" : "warning"}>{(f.confidence * 100).toFixed(0)}% conf</Badge>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Risk Scenarios" />
        <div className="card-body">
          {sLoading ? <Skeleton lines={3} />
          : sError ? <ErrorState />
          : !scenarios?.length ? <EmptyState title="No scenarios defined" />
          : <ul className="space-y-2">
              {scenarios.map((s) => (
                <li key={s.name} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold capitalize text-slate-900 dark:text-slate-100">{s.name.replace(/_/g, " ")}</span>
                    <Badge tone={s.predicted_level === "critical" ? "danger" : s.predicted_level === "high" ? "warning" : "info"} size="sm">{s.predicted_level}</Badge>
                    <span className="ml-auto text-[10px] text-slate-500">{Math.round(s.predicted_score * 100)}% risk score</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {Object.entries(s.adjustments ?? {}).map(([k, v]) => `${k}: ${v > 0 ? "+" : ""}${v}`).join(" · ") || "Baseline projection"}
                  </p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}

function GovernanceTab() {
  const { data: policies, isLoading: pLoading, isError: pError, refetch: pRefetch } = useQuery({
    queryKey: governanceKeys.policies(), queryFn: getPolicies,
  });
  const { data: decisions, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: governanceKeys.decisions(), queryFn: getDecisions,
  });
  const { data: stats, isLoading: sLoading, isError: sError, refetch: sRefetch } = useQuery({
    queryKey: governanceKeys.stats(), queryFn: getGovernanceStats,
  });

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        {sLoading ? Array.from({length: 4}).map((_, i) => (<Metric key={i} label="—" value="…" />))
        : sError ? <ErrorState onRetry={sRefetch} />
        : <>
            <Metric label="Policies" value={stats?.total_policies ?? "—"} />
            <Metric label="Compliant" value={stats?.compliant_decisions ?? "—"} hint="Compliant decisions" />
            <Metric label="Decisions" value={stats?.total_decisions ?? "—"} />
            <Metric label="Violations" value={stats?.total_violations ?? "—"} />
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
                {(policies ?? []).map((p) => {
                  const v = toPolicyView(p);
                  return (
                    <TR key={p.policy_id}>
                      <TD className="font-medium">{p.name}</TD>
                      <TD>{p.scope ?? "—"}</TD>
                      <TD><Badge tone={v.enabled ? "success" : "warning"} size="sm">{v.statusText}</Badge></TD>
                      <TD>v{p.version}</TD>
                      <TD>{(p.rules?.length ?? 0)}</TD>
                      <TD className="text-[10px]">{formatRelative(p.updated_at)}</TD>
                    </TR>
                  );
                })}
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
              <THead><TR><TH>Title</TH><TH>Decision</TH><TH>Authority</TH><TH>Date</TH></TR></THead>
              <TBody>
                {(decisions ?? []).map(toDecisionView).map((d) => (
                  <TR key={d.id}>
                    <TD className="font-medium">{d.subject}</TD>
                    <TD><Badge tone="neutral" size="sm">{d.outcome}</Badge></TD>
                    <TD>{d.actor ?? "—"}</TD>
                    <TD className="text-[10px]">{formatRelative(d.timestampMillis)}</TD>
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

function ImpactTab() {
  const { data: assessments } = useQuery({
    queryKey: complianceKeys.assessments(), queryFn: getComplianceAssessments,
  });
  const { data: scenarios } = useQuery({
    queryKey: riskKeys.scenarios(), queryFn: getRiskScenarios,
  });

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Metric label="Compliance Assessments" value={assessments?.length ?? "—"} hint="Total impact evaluations" />
        <Metric label="Risk Scenarios" value={scenarios?.length ?? "—"} hint="Modelled risk events" />
      </section>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Impact Assessment</h3>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Run a compliance assessment or risk forecast to generate impact data. Results appear in the Overview and Risk Analysis tabs above.</p>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-slate-900 dark:text-slate-100">Regulatory Impact</h4>
            <p className="mt-1 text-[11px] text-slate-500">Evaluate how regulatory changes affect your current obligations, policies, and risk posture.</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-slate-900 dark:text-slate-100">Dependency Impact</h4>
            <p className="mt-1 text-[11px] text-slate-500">Assess downstream effects of policy changes across entities, regulations, and controls.</p>
          </div>
        </div>
      </Card>
    </div>
  );
}
