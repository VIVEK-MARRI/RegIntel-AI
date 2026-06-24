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
import { formatNumber, formatRelative, truncate } from "@/lib/format";
import type { ComplianceAssessment } from "@/types";

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
    queryKey: ["compliance", "assessments"], queryFn: getComplianceAssessments,
  });
  const run = useMutation({ mutationFn: runCompliance, onSuccess: () => refetch() });
  const toast = useToast();
  const [scope, setScope] = useState("");
  const [policiesStr, setPoliciesStr] = useState("");
  const [selected, setSelected] = useState<ComplianceAssessment | null>(null);

  const avgScore = assessments?.length
    ? Math.round(assessments.reduce((s, a) => s + a.overall_score, 0) / assessments.length * 100)
    : null;

  const riskTone = (level: string) => level === "critical" ? "danger" : level === "high" ? "warning" : level === "medium" ? "info" : "success";

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

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Metric label="Compliance Score" value={avgScore !== null ? `${avgScore}%` : "—"} hint={assessments ? `${assessments.length} assessment(s)` : "Loading…"} />
        <Metric label="Assessments" value={assessments?.length ?? "—"} />
        <Metric label="Open Gaps" value={assessments?.reduce((s, a) => s + (a.gaps?.length ?? 0), 0) ?? "—"} />
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
          <CardHeader title={selected.scope} actions={<Badge tone={riskTone(selected.risk_level)}>{selected.risk_level}</Badge>} />
          <div className="card-body space-y-4">
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Obligations ({(selected.obligations ?? []).length})</h4>
              <ul className="mt-2 space-y-1.5">
                {(selected.obligations ?? []).map((o) => (
                  <li key={o.obligation_id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <span className="flex-1 font-medium text-slate-900 dark:text-slate-100">{o.title ?? "—"}</span>
                    <Badge tone={o.severity === "critical" ? "danger" : o.severity === "high" ? "warning" : "info"} size="sm">{o.severity}</Badge>
                    <Badge tone={o.status === "met" ? "success" : o.status === "breached" ? "danger" : "warning"} size="sm">{o.status}</Badge>
                  </li>
                ))}
              </ul>
            </section>
            {(selected.gaps ?? []).length ? (
              <section>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Gaps ({(selected.gaps ?? []).length})</h4>
                <ul className="mt-2 space-y-1.5">
                  {(selected.gaps ?? []).map((g) => (
                    <li key={g.gap_id} className="rounded-lg border border-red-200 bg-red-50/40 px-3 py-2 text-xs dark:border-red-900/40 dark:bg-red-950/20">
                      <p className="font-medium text-red-800 dark:text-red-200">{g.description}</p>
                      <p className="mt-1 text-red-600 dark:text-red-400">Actions: {(g.recommended_actions ?? []).join(", ") || "—"}</p>
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
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{a.scope}</span>
                    <Badge tone={riskTone(a.risk_level)}>{a.risk_level}</Badge>
                    <Badge tone="brand" size="sm">{Math.round(a.overall_score * 100)}%</Badge>
                    <span className="ml-auto text-[10px] text-slate-500">{formatRelative(a.generated_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{(a.obligations?.length ?? 0)} obligations · {(a.gaps?.length ?? 0)} gaps</p>
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
    queryKey: ["risk", "forecasts"], queryFn: getRiskForecasts,
  });
  const { data: scenarios, isLoading: sLoading, isError: sError } = useQuery({
    queryKey: ["risk", "scenarios"], queryFn: getRiskScenarios,
  });
  const run = useMutation({ mutationFn: forecastRisk });
  const toast = useToast();
  const [horizon, setHorizon] = useState(30);
  const [baseline, setBaseline] = useState(60);

  async function handleForecast() {
    try {
      const result = await run.mutateAsync({ horizon_days: horizon, baseline_score: baseline });
      toast.push({ title: "Forecast generated", description: `${result.horizon_days}-day: ${Math.round(result.projected_score)}/100`, tone: "success" });
    } catch (err) {
      toast.push({ title: "Forecast failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    }
  }

  const scoreTone = (score: number) => score > 75 ? "danger" : score > 50 ? "warning" : "success";

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Metric label="Active Forecasts" value={forecasts?.length ?? "—"} />
        <Metric label="Avg Projected Score" value={forecasts?.length ? `${Math.round(forecasts.reduce((s, f) => s + f.projected_score, 0) / forecasts.length)}` : "—"} />
        <Metric label="Scenarios" value={scenarios?.length ?? "—"} />
        <Metric label="Avg Confidence" value={forecasts?.length ? `${Math.round(forecasts.reduce((s, f) => s + f.confidence, 0) / forecasts.length * 100)}%` : "—"} />
      </section>

      <Card padding="md">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Generate Risk Forecast</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[120px_120px_auto]">
          <Field label="Horizon (days)" id="risk-horizon">
            <Input id="risk-horizon" type="number" min={1} max={365} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} />
          </Field>
          <Field label="Baseline score" id="risk-baseline">
            <Input id="risk-baseline" type="number" min={0} max={100} value={baseline} onChange={(e) => setBaseline(Number(e.target.value))} />
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
                      <span className="text-slate-500">{formatNumber(f.projected_score)} / 100</span>
                    </div>
                    <ProgressBar value={f.projected_score} max={100} tone={scoreTone(f.projected_score)} className="mt-1.5" />
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
                <li key={s.scenario_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{s.name}</span>
                    <Badge tone={s.impact === "critical" ? "danger" : s.impact === "high" ? "warning" : "info"} size="sm">{s.impact}</Badge>
                    <span className="ml-auto text-[10px] text-slate-500">{Math.round(s.probability * 100)}% probability</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{s.description}</p>
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
    queryKey: ["governance", "policies"], queryFn: getPolicies,
  });
  const { data: decisions, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: ["governance", "decisions"], queryFn: getDecisions,
  });
  const { data: stats, isLoading: sLoading, isError: sError, refetch: sRefetch } = useQuery({
    queryKey: ["governance", "stats"], queryFn: getGovernanceStats,
  });

  return (
    <div className="space-y-4">
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
                    <TD>{p.scope ?? "—"}</TD>
                    <TD><Badge tone={p.status === "active" ? "success" : p.status === "deprecated" ? "danger" : "warning"} size="sm">{p.status}</Badge></TD>
                    <TD>v{p.version}</TD>
                    <TD>{(p.rules?.length ?? 0)}</TD>
                    <TD className="text-[10px]">{formatRelative(p.updated_at)}</TD>
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
              <THead><TR><TH>Title</TH><TH>Decision</TH><TH>Authority</TH><TH>Date</TH></TR></THead>
              <TBody>
                {decisions.map((d) => (
                  <TR key={d.decision_id}>
                    <TD className="font-medium">{d.subject ?? truncate(d.rationale, 60)}</TD>
                    <TD><Badge tone={d.outcome === "approved" ? "success" : d.outcome === "rejected" ? "danger" : "warning"} size="sm">{d.outcome}</Badge></TD>
                    <TD>{d.approver ?? "—"}</TD>
                    <TD className="text-[10px]">{formatRelative(d.created_at)}</TD>
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
    queryKey: ["compliance", "assessments"], queryFn: getComplianceAssessments,
  });
  const { data: scenarios } = useQuery({
    queryKey: ["risk", "scenarios"], queryFn: getRiskScenarios,
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
