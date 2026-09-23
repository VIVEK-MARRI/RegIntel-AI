import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { formatNumber, formatRelative } from "@/lib/format";
import { toMillis } from "@/lib/dates";
import {
  complianceKeys,
  documentsKeys,
  governanceKeys,
  riskKeys,
} from "@/lib/queryKeys";
import {
  getComplianceAssessmentsFiltered,
  getComplianceStats,
  getComplianceTrend,
  runCompliance,
} from "@/services/api/complianceApi";
import { getDocuments } from "@/services/api/documentsApi";
import {
  forecastRisk,
  getForecastStats,
  getRiskForecasts,
  getRiskScenarios,
} from "@/services/api/riskApi";
import {
  getApprovalPolicies,
  getDecisions,
  getGovernanceStats,
  getPolicies,
  recheckDecision,
  updatePolicy,
} from "@/services/api/governanceApi";
import { toPolicyView } from "@/adapters/governance";
import type {
  AffectedArea,
  ComplianceGap,
  RecommendedAction,
  RiskAssessment,
  RiskFactor,
} from "@/types/api/compliance";
import type { ForecastPoint, RiskForecast } from "@/types/api/risk";
import type {
  GovernanceDecision,
  PolicyCheckResult,
  PolicyRule,
  PolicyViolation,
} from "@/types/api/governance";

/**
 * Compliance workbench: assessment, forecast, policies, decisions.
 *
 * Backend-verified semantics (code, not inherited UI assumptions):
 * - Risk scores run 0–1 with HIGHER = MORE RISK. Backend bands
 *   (RiskScorer._to_level): critical ≥ 0.85, high ≥ 0.65, medium ≥ 0.4,
 *   else low. Scores are shown as numbers, never as percentages.
 * - POST /compliance-risk/assess is synchronous and reads ONLY
 *   document_id/diff_id/impact_report_id/source/context. A request with no
 *   references scores default medium signals — the form says so honestly.
 * - Forecast confidence echoes the request; action/explanation confidences
 *   are backend constants. None is displayed as a model signal.
 * - Forecast points[]/series are genuine series (SVG chart justified);
 *   forecasting trend is a single object (no chart built for it).
 * - Review/alerts/recommendations/changes are separate backend modules with
 *   their own workflows and are NOT part of this page (documented).
 */

type TabId = "assessment" | "forecast" | "policies" | "decisions";

const TABS = [
  { id: "assessment" as const, label: "Assessment" },
  { id: "forecast" as const, label: "Forecast" },
  { id: "policies" as const, label: "Policies" },
  { id: "decisions" as const, label: "Decisions" },
];

const RISK_LEVELS = ["low", "medium", "high", "critical"];
const RISK_CATEGORIES = [
  "regulatory_exposure", "compliance_gap", "operational", "financial",
  "reputational", "strategic", "technology", "legal",
];
const DECISION_TYPES = [
  "answer", "recommendation", "risk_assessment", "forecast",
  "classification", "extraction", "summarization", "other",
];
const POLICY_SCOPES = ["global", "regulator", "document", "workflow", "model"];
const ASSESS_SOURCES = ["manual", "monitoring", "ingestion", "change_detection"];

const SCORE_BANDS_NOTE =
  "Scores run 0–1; higher means more risk. Backend bands: critical ≥ 0.85, high ≥ 0.65, medium ≥ 0.4, else low.";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
function levelTone(level: string): Tone {
  switch (level) {
    case "critical": return "danger";
    case "high": return "warning";
    case "medium": return "info";
    case "low": return "success";
    default: return "neutral";
  }
}

/** Runtime guards: backend arrays/objects are trusted but never assumed. */
function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function fmtScore(v: unknown): string {
  const n = num(v);
  return n === null ? "—" : formatNumber(n, 2);
}
function fmtDuration(ms: unknown): string | null {
  const n = num(ms);
  if (n === null || n <= 0) return null;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`;
}
function fmtDate(ms: unknown): string {
  const m = toMillis(ms);
  if (m === null) return "date unknown";
  const d = new Date(m);
  return Number.isNaN(d.getTime()) ? "date unknown" : d.toLocaleDateString();
}

export function CompliancePage() {
  const [tab, setTab] = useState<TabId>("assessment");

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Compliance</h1>
        <p className="page-description">
          Assess regulatory risk, project it forward, and review the policies and
          decisions that govern it.
        </p>
      </header>

      <Tabs
        items={TABS}
        value={tab}
        onChange={(id) => setTab(id as TabId)}
        label="Compliance sections"
        idPrefix="compliance"
      />

      <div role="tabpanel" id={`compliance-panel-${tab}`} aria-labelledby={`compliance-tab-${tab}`} tabIndex={0}>
        {tab === "assessment" && <AssessmentTab />}
        {tab === "forecast" && <ForecastTab />}
        {tab === "policies" && <PoliciesTab />}
        {tab === "decisions" && <DecisionsTab />}
      </div>
    </div>
  );
}

/* ─── shared SVG charts (real series only) ─────────────────────────── */

function SeriesChart({
  points,
  ariaLabel,
  height = 140,
}: {
  points: { x: number; y: number; label: string }[];
  ariaLabel: string;
  height?: number;
}) {
  const W = 320;
  const H = height;
  const PAD = 8;
  if (points.length === 0) return null;
  const min = Math.min(...points.map((p) => p.y), 0);
  const max = Math.max(...points.map((p) => p.y), 1);
  const span = max - min || 1;
  const px = (i: number) =>
    points.length === 1 ? W / 2 : PAD + (i * (W - PAD * 2)) / (points.length - 1);
  const py = (y: number) => PAD + (1 - (y - min) / span) * (H - PAD * 2 - 14);
  const line = points.map((p, i) => `${px(i)},${py(p.y)}`).join(" ");
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      aria-label={ariaLabel}
      style={{ height }}
    >
      <line x1={PAD} y1={H - 14} x2={W - PAD} y2={H - 14}
        className="stroke-slate-200 dark:stroke-slate-700" strokeWidth={1} />
      <polyline points={line} fill="none" className="stroke-brand-500" strokeWidth={2} />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={px(i)} cy={py(p.y)} r={3} className="fill-brand-600 dark:fill-brand-400">
            <title>{p.label}</title>
          </circle>
        </g>
      ))}
      <text x={PAD} y={H - 2} fontSize={9} className="fill-slate-500">{points[0].label}</text>
      {points.length > 1 && (
        <text x={W - PAD} y={H - 2} fontSize={9} textAnchor="end" className="fill-slate-500">
          {points[points.length - 1].label}
        </text>
      )}
    </svg>
  );
}

function BandChart({ points }: { points: ForecastPoint[] }) {
  const W = 320;
  const H = 140;
  const PAD = 8;
  const px = (i: number) =>
    points.length === 1 ? W / 2 : PAD + (i * (W - PAD * 2)) / (points.length - 1);
  const py = (y: number) => PAD + (1 - Math.min(1, Math.max(0, y))) * (H - PAD * 2 - 14);
  const upper = points.map((p, i) => `${px(i)},${py(num(p.upper_bound) ?? num(p.predicted_score) ?? 0)}`).join(" ");
  const lower = [...points]
    .reverse()
    .map((p, i) => `${px(points.length - 1 - i)},${py(num(p.lower_bound) ?? num(p.predicted_score) ?? 0)}`)
    .join(" ");
  const line = points
    .map((p, i) => `${px(i)},${py(num(p.predicted_score) ?? 0)}`)
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      aria-label={`Projected risk over ${points.length} points with a projected range band.`}
      style={{ height: H }}
    >
      <polygon points={`${upper} ${lower}`} className="fill-brand-100 dark:fill-brand-950/50" />
      <polyline points={line} fill="none" className="stroke-brand-600" strokeWidth={2} />
      <text x={PAD} y={H - 2} fontSize={9} className="fill-slate-500">{fmtDate(points[0].timestamp)}</text>
      {points.length > 1 && (
        <text x={W - PAD} y={H - 2} fontSize={9} textAnchor="end" className="fill-slate-500">
          {fmtDate(points[points.length - 1].timestamp)}
        </text>
      )}
    </svg>
  );
}

/* ─── assessment tab ───────────────────────────────────────────────── */

const ASSESS_PAGE_SIZE = 50;

function AssessmentTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [docId, setDocId] = useState("");
  const [source, setSource] = useState("manual");
  const [diffId, setDiffId] = useState("");
  const [impactId, setImpactId] = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  const [catFilter, setCatFilter] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<RiskAssessment | null>(null);

  const stats = useQuery({ queryKey: complianceKeys.stats(), queryFn: getComplianceStats });
  const docs = useQuery({ queryKey: documentsKeys.list({}), queryFn: () => getDocuments() });

  const listQuery = useMemo(
    () => ({
      risk_level: levelFilter || undefined,
      category: catFilter || undefined,
      page: page + 1,
      page_size: ASSESS_PAGE_SIZE,
    }),
    [levelFilter, catFilter, page]
  );
  const history = useQuery({
    queryKey: complianceKeys.assessmentsFiltered(listQuery),
    queryFn: () => getComplianceAssessmentsFiltered(listQuery),
  });

  const run = useMutation({
    mutationFn: runCompliance,
    onSuccess: (result) => {
      setSelected(result);
      // Dashboard reads the same assessments() family: prefix invalidation
      // refreshes it without touching other domains.
      void qc.invalidateQueries({ queryKey: [...complianceKeys.all, "assessments"] });
      void qc.invalidateQueries({ queryKey: complianceKeys.stats() });
      toast.push({
        title: "Assessment complete",
        description: `${result.assessment_id} — ${result.risk_level} (${fmtScore(result.risk_score)})`,
        tone: "success",
      });
    },
  });

  const handleRun = () => {
    if (run.isPending) return;
    run.mutate({
      document_id: docId || undefined,
      diff_id: diffId.trim() || undefined,
      impact_report_id: impactId.trim() || undefined,
      source,
    });
  };

  const list = history.data ?? [];
  const shortPage = list.length < ASSESS_PAGE_SIZE;

  return (
    <div className="space-y-4">
      <section aria-label="Assessment overview" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : stats.isError ? (
          <div className="sm:col-span-2 lg:col-span-4">
            <ErrorState title="Assessment statistics unavailable" error={stats.error} onRetry={() => void stats.refetch()} />
          </div>
        ) : (
          <>
            <Metric label="Assessments" value={stats.data.total_assessments.toLocaleString()} hint="Stored assessments" />
            <Metric
              label="Need attention"
              value={(stats.data.critical_risks + stats.data.high_risks).toLocaleString()}
              hint={`${stats.data.critical_risks} critical · ${stats.data.high_risks} high (backend counts)`}
            />
            <Metric label="Open gaps" value={stats.data.total_compliance_gaps.toLocaleString()} hint={`${stats.data.total_recommended_actions} recommended actions`} />
            <Metric label="Average risk score" value={fmtScore(stats.data.average_risk_score)} hint="0–1 across stored assessments; higher is worse" />
          </>
        )}
      </section>

      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Run assessment</h2>
        <p className="meta-text mb-3 mt-0.5">
          Synchronous: the request analyses and returns one assessment. With no
          document or reference selected, the backend scores default medium
          signals — a baseline, not a scoped finding.
        </p>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_180px]">
          <Field label="Document (optional)" id="assess-doc" hint="Grounds the assessment in a stored document">
            <Select id="assess-doc" value={docId} onChange={(e) => setDocId(e.target.value)}>
              <option value="">Baseline — no document</option>
              {(docs.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title} ({d.status})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Source" id="assess-source">
            <Select id="assess-source" value={source} onChange={(e) => setSource(e.target.value)}>
              {ASSESS_SOURCES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="Change ID (optional)" id="assess-diff" hint="References a detected change">
            <Input id="assess-diff" value={diffId} onChange={(e) => setDiffId(e.target.value)} placeholder="chg-…" />
          </Field>
          <Field label="Impact report ID (optional)" id="assess-impact" hint="References an impact report">
            <Input id="assess-impact" value={impactId} onChange={(e) => setImpactId(e.target.value)} placeholder="imp-…" />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" loading={run.isPending} disabled={run.isPending} onClick={handleRun}>
              Run assessment
            </Button>
          </div>
        </div>
        {docs.isError && (
          <p className="meta-text mt-2">Document list unavailable — baseline assessments still work.</p>
        )}
        {run.isPending && (
          <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
            <p className="text-sm font-medium text-brand-900 dark:text-brand-100">Assessment is running…</p>
            <p className="mt-1 text-xs text-brand-800/80 dark:text-brand-200/80">
              Scoring risk factors, areas, gaps, and actions in one request. Please wait.
            </p>
          </div>
        )}
        {run.isError && (
          <div className="mt-3">
            <ErrorState title="Assessment failed" error={run.error} onRetry={handleRun} />
          </div>
        )}
      </Card>

      {selected && <AssessmentDetail assessment={selected} />}

      <Card padding="none">
        <CardHeader
          title="Assessment history"
          description="Newest first"
          actions={
            <div className="flex gap-2">
              <Select aria-label="Filter by risk level" value={levelFilter} onChange={(e) => { setLevelFilter(e.target.value); setPage(0); }} className="text-xs">
                <option value="">All levels</option>
                {RISK_LEVELS.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </Select>
              <Select aria-label="Filter by category" value={catFilter} onChange={(e) => { setCatFilter(e.target.value); setPage(0); }} className="text-xs">
                <option value="">All categories</option>
                {RISK_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </div>
          }
        />
        <div className="card-body" aria-live="polite">
          {history.isPending ? (
            <Skeleton lines={4} />
          ) : history.isError ? (
            <ErrorState title="Assessment history unavailable" error={history.error} onRetry={() => void history.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState
              title="No assessments yet"
              description={levelFilter || catFilter ? "No stored assessments match these filters." : "Run an assessment above to create the first record."}
            />
          ) : (
            <>
              <ul className="space-y-2">
                {list.map((a) => (
                  <li key={a.assessment_id}>
                    <button
                      type="button"
                      onClick={() => setSelected(a)}
                      aria-pressed={selected?.assessment_id === a.assessment_id}
                      className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={levelTone(a.risk_level)} size="sm">{a.risk_level}</Badge>
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {fmtScore(a.risk_score)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs text-slate-500 dark:text-slate-400">
                          {a.document_id ?? a.assessment_id}
                        </span>
                        <span className="meta-text ml-auto">{a.generated_at ? formatRelative(a.generated_at) : "time unknown"}</span>
                      </div>
                      <p className="meta-text mt-1">
                        {arr(a.risk_categories).join(" · ") || "no categories"} ·{" "}
                        {arr(a.compliance_gaps).length} gap(s) · {arr(a.recommended_actions).length} action(s)
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
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
    </div>
  );
}

function AssessmentDetail({ assessment: a }: { assessment: RiskAssessment }) {
  const factors = arr<RiskFactor>(
    typeof a.explanation === "object" && a.explanation !== null
      ? (a.explanation as { top_factors?: unknown }).top_factors
      : []
  );
  const explSummary =
    typeof a.explanation === "string"
      ? a.explanation
      : str((a.explanation as { summary?: unknown })?.summary);
  const scoringMethod =
    typeof a.explanation === "object" && a.explanation !== null
      ? str((a.explanation as { scoring_method?: unknown })?.scoring_method)
      : null;
  const duration = fmtDuration(a.duration_ms);
  const trend = useQuery({
    queryKey: complianceKeys.trend(a.document_id ?? undefined),
    queryFn: () => getComplianceTrend(a.document_id ?? undefined),
  });
  const trendPoints = (trend.data?.points ?? [])
    .filter((p) => num(p.timestamp) !== null && num(p.risk_score) !== null)
    .map((p) => ({
      x: toMillis(p.timestamp) ?? 0,
      y: p.risk_score,
      label: `${fmtScore(p.risk_score)} (${p.risk_level}) · ${fmtDate(p.timestamp)}`,
    }));

  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={levelTone(a.risk_level)}>{a.risk_level}</Badge>
          <span className="text-2xl font-bold text-slate-900 dark:text-white">{fmtScore(a.risk_score)}</span>
          <span className="meta-text ml-auto">{a.generated_at ? formatRelative(a.generated_at) : "time unknown"}</span>
        </div>
        <h3 className="mt-2 text-base font-bold text-slate-900 dark:text-white">
          {a.document_id ?? a.assessment_id}
        </h3>
        <p className="meta-text mt-1">{SCORE_BANDS_NOTE}</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="meta-text">Source</dt>
            <dd className="text-slate-700 dark:text-slate-200">{a.source}</dd>
          </div>
          <div>
            <dt className="meta-text">Regulatory exposure</dt>
            <dd className="text-slate-700 dark:text-slate-200">{fmtScore(a.regulatory_exposure)} (0–1)</dd>
          </div>
          <div>
            <dt className="meta-text">Previous score</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {a.historical_risk_score !== null && a.historical_risk_score !== undefined
                ? `${fmtScore(a.historical_risk_score)} · trend ${a.trend || "flat"}`
                : "no prior assessment"}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Assessed{duration ? ` in ${duration}` : ""}</dt>
            <dd className="break-all font-mono text-xs text-slate-600 dark:text-slate-300">{a.assessment_id}</dd>
          </div>
        </dl>
        {(a.diff_id || a.impact_report_id) && (
          <p className="meta-text mt-2">
            {[a.diff_id && `change ${a.diff_id}`, a.impact_report_id && `impact ${a.impact_report_id}`]
              .filter(Boolean).join(" · ")}
          </p>
        )}

        {explSummary && (
          <section aria-label="Analysis" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Analysis</h4>
            <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{explSummary}</p>
            {scoringMethod && <p className="meta-text mt-1">Scoring method: {scoringMethod}</p>}
          </section>
        )}

        {factors.length > 0 && (
          <section aria-label="Risk drivers" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Risk drivers ({factors.length})
            </h4>
            <ul className="mt-2 space-y-1.5">
              {factors.map((f, i) => (
                <li key={str(f.factor_id) ?? `factor-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{str(f.name) ?? "Unnamed factor"}</span>
                    <Badge size="sm">{str(f.category) ?? "uncategorized"}</Badge>
                    <span className="meta-text ml-auto">contribution {fmtScore(f.contribution)}</span>
                  </div>
                  {str(f.explanation) && <p className="mt-1 text-slate-600 dark:text-slate-300">{f.explanation}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-label="Risk trajectory" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Risk trajectory</h4>
          {trend.isPending ? (
            <Skeleton className="mt-2 h-28" />
          ) : trend.isError ? (
            <p className="meta-text mt-2">Trajectory unavailable.</p>
          ) : trendPoints.length >= 2 ? (
            <>
              <div className="mt-2 max-w-md">
                <SeriesChart
                  points={trendPoints}
                  ariaLabel={`Risk trajectory: ${trendPoints.length} assessments, direction ${trend.data?.direction ?? "flat"}, change ${fmtScore(trend.data?.delta)}.`}
                />
              </div>
              <p className="meta-text mt-1">
                Direction {trend.data?.direction ?? "flat"} · change {fmtScore(trend.data?.delta)}
                {trend.data?.document_id ? ` · scoped to document ${trend.data.document_id}` : " · across all assessments"}
              </p>
            </>
          ) : (
            <p className="meta-text mt-2">
              {trendPoints.length === 1 ? "A single assessment — trajectory needs at least two points." : "No assessment history for a trajectory."}
              {trend.data && ` Direction ${trend.data.direction}.`}
            </p>
          )}
        </section>

        <section aria-label="Affected areas" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Affected areas ({arr(a.affected_areas).length})
          </h4>
          {arr<AffectedArea>(a.affected_areas).length === 0 ? (
            <p className="meta-text mt-2">No affected areas recorded.</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {arr<AffectedArea>(a.affected_areas).map((ar, i) => (
                <li key={i} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{str(ar.area) ?? "unknown area"}</span>
                    <span className="meta-text ml-auto">exposure {fmtScore(ar.exposure_score)} (0–1)</span>
                  </div>
                  {str(ar.rationale) && <p className="mt-1 text-slate-600 dark:text-slate-300">{ar.rationale}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Compliance gaps" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Compliance gaps ({arr(a.compliance_gaps).length})
          </h4>
          {arr(a.compliance_gaps).length === 0 ? (
            <p className="meta-text mt-2">No gaps detected in this assessment.</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {arr<ComplianceGap>(a.compliance_gaps).map((g, i) => (
                <li key={str(g.gap_id) ?? `gap-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{str(g.area) ?? "unknown area"}</span>
                    <Badge tone={levelTone(str(g.severity) ?? "")} size="sm">{str(g.severity) ?? "unknown severity"}</Badge>
                  </div>
                  <p className="mt-1 text-slate-700 dark:text-slate-200">{str(g.description) ?? "No description."}</p>
                  {str(g.regulatory_basis) && <p className="meta-text mt-1">Basis: {g.regulatory_basis}</p>}
                  {str(g.remediation_action_id) && (
                    <p className="meta-text mt-1">Linked recommended action: {g.remediation_action_id}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Recommended actions" className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Recommended actions ({arr(a.recommended_actions).length})
          </h4>
          {arr(a.recommended_actions).length === 0 ? (
            <p className="meta-text mt-2">No recommended actions for this assessment.</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {arr<RecommendedAction>(a.recommended_actions).map((r, i) => (
                <li key={str(r.action_id) ?? `action-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{str(r.title) ?? "Untitled action"}</span>
                    <Badge size="sm">{str(r.action_type) ?? "action"}</Badge>
                    {str(r.priority) && <Badge tone={levelTone(r.priority as string)} size="sm">priority: {r.priority}</Badge>}
                  </div>
                  {str(r.description) && <p className="mt-1 text-slate-600 dark:text-slate-300">{r.description}</p>}
                  {str(r.rationale) && <p className="meta-text mt-1">Why: {r.rationale}</p>}
                  {num(r.estimated_effort_hours) !== null && (r.estimated_effort_hours as number) > 0 && (
                    <p className="meta-text mt-1">Estimated effort: {r.estimated_effort_hours as number}h</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Card>
  );
}

/* ─── forecast tab ─────────────────────────────────────────────────── */

function ForecastTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [docId, setDocId] = useState("");
  const [horizon, setHorizon] = useState(30);
  const [latest, setLatest] = useState<RiskForecast | null>(null);

  const stats = useQuery({ queryKey: riskKeys.stats(), queryFn: getForecastStats });
  const docs = useQuery({ queryKey: documentsKeys.list({}), queryFn: () => getDocuments() });
  const forecasts = useQuery({ queryKey: riskKeys.forecasts(), queryFn: getRiskForecasts });
  const scenarios = useQuery({ queryKey: riskKeys.scenarios(), queryFn: getRiskScenarios });

  const run = useMutation({
    mutationFn: forecastRisk,
    onSuccess: (result) => {
      setLatest(result);
      // Scenarios derive from the latest forecast score: refresh both.
      void qc.invalidateQueries({ queryKey: riskKeys.forecasts() });
      void qc.invalidateQueries({ queryKey: riskKeys.scenarios() });
      void qc.invalidateQueries({ queryKey: riskKeys.stats() });
      toast.push({
        title: "Forecast ready",
        description: `${result.horizon_days}-day horizon — ${result.predicted_risk_level} (${fmtScore(result.predicted_risk_score)})`,
        tone: "success",
      });
    },
  });

  const handleRun = () => {
    if (run.isPending) return;
    run.mutate({ document_id: docId || undefined, horizon_days: horizon });
  };

  return (
    <div className="space-y-4">
      <section aria-label="Forecast overview" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : stats.isError ? (
          <div className="sm:col-span-2 lg:col-span-4">
            <ErrorState title="Forecast statistics unavailable" error={stats.error} onRetry={() => void stats.refetch()} />
          </div>
        ) : (
          <>
            <Metric label="Forecasts" value={stats.data.total_forecasts.toLocaleString()} hint="Stored forecasts" />
            <Metric label="Average horizon" value={`${formatNumber(stats.data.average_horizon_days, 1)} days`} hint="Across stored forecasts" />
            <Metric label="Drift events" value={stats.data.drift_detected.toLocaleString()} hint={`Drift rate ${formatNumber(stats.data.drift_rate, 3)}`} />
            <Metric label="Last forecast" value={stats.data.last_forecast_at ? formatRelative(stats.data.last_forecast_at) : "—"} hint="Most recent generation" />
          </>
        )}
      </section>

      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Run forecast</h2>
        <p className="meta-text mb-3 mt-0.5">
          Projects risk over a horizon with a linear model. With no document
          selected the projection uses a neutral baseline, not your data.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_140px_auto]">
          <Field label="Document (optional)" id="forecast-doc">
            <Select id="forecast-doc" value={docId} onChange={(e) => setDocId(e.target.value)}>
              <option value="">Baseline — no document</option>
              {(docs.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title} ({d.status})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Horizon (days)" id="forecast-horizon" hint="1–365">
            <Input
              id="forecast-horizon"
              type="number"
              min={1}
              max={365}
              value={horizon}
              onChange={(e) => setHorizon(Math.min(365, Math.max(1, Number(e.target.value) || 30)))}
            />
          </Field>
          <div className="flex items-end">
            <Button variant="primary" loading={run.isPending} disabled={run.isPending} onClick={handleRun}>
              Run forecast
            </Button>
          </div>
        </div>
        {run.isPending && (
          <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4 dark:border-brand-900/40 dark:bg-brand-950/20" role="status">
            <p className="text-sm font-medium text-brand-900 dark:text-brand-100">Forecast is running…</p>
            <p className="mt-1 text-xs text-brand-800/80 dark:text-brand-200/80">
              Fitting the model and projecting the horizon in one request. Please wait.
            </p>
          </div>
        )}
        {run.isError && (
          <div className="mt-3">
            <ErrorState title="Forecast failed" error={run.error} onRetry={handleRun} />
          </div>
        )}
      </Card>

      {latest && <ForecastResult forecast={latest} />}

      <Card padding="none">
        <CardHeader title="Forecasts" description="Stored projections, newest first" />
        <div className="card-body" aria-live="polite">
          {forecasts.isPending ? (
            <Skeleton lines={4} />
          ) : forecasts.isError ? (
            <ErrorState title="Forecasts unavailable" error={forecasts.error} onRetry={() => void forecasts.refetch()} />
          ) : (forecasts.data ?? []).length === 0 ? (
            <EmptyState title="No forecasts yet" description="Run a forecast above to create the first projection." />
          ) : (
            <ul className="space-y-2">
              {(forecasts.data ?? []).map((f) => (
                <li key={f.forecast_id}>
                  <button
                    type="button"
                    onClick={() => setLatest(f)}
                    aria-pressed={latest?.forecast_id === f.forecast_id}
                    className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={levelTone(f.predicted_risk_level)} size="sm">{f.predicted_risk_level}</Badge>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{fmtScore(f.predicted_risk_score)}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{f.horizon_days}-day horizon</span>
                      {f.drift_detected && <Badge tone="warning" size="sm">drift</Badge>}
                      <span className="meta-text ml-auto">{f.generated_at ? formatRelative(f.generated_at) : "time unknown"}</span>
                    </div>
                    <p className="meta-text mt-1">
                      {arr(f.points).length} projected point(s) · method {str(f.method) ?? "unknown"}
                      {f.document_id ? ` · document ${f.document_id}` : " · baseline"}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Scenarios" description="Best / baseline / worst projections from the latest forecast" />
        <div className="card-body" aria-live="polite">
          {scenarios.isPending ? (
            <Skeleton lines={3} />
          ) : scenarios.isError ? (
            <ErrorState title="Scenarios unavailable" error={scenarios.error} onRetry={() => void scenarios.refetch()} />
          ) : (scenarios.data ?? []).length === 0 ? (
            <EmptyState title="No scenarios" description="Scenarios appear once a forecast exists." />
          ) : (
            <ul className="space-y-2">
              {(scenarios.data ?? []).map((s) => (
                <li key={s.name} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold capitalize text-slate-900 dark:text-slate-100">
                      {s.name.replace(/_/g, " ")}
                    </span>
                    <Badge tone={levelTone(s.predicted_level)} size="sm">{s.predicted_level}</Badge>
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{fmtScore(s.predicted_score)}</span>
                  </div>
                  <p className="meta-text mt-1">
                    {Object.entries(s.adjustments ?? {})
                      .map(([k, v]) => `${k}: ${v > 0 ? "+" : ""}${v}`)
                      .join(" · ") || "Baseline projection (no adjustments)"}
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

function ForecastResult({ forecast: f }: { forecast: RiskForecast }) {
  const points = arr<ForecastPoint>(f.points).filter(
    (p) => num(p.timestamp) !== null && num(p.predicted_score) !== null
  );
  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={levelTone(f.predicted_risk_level)}>{f.predicted_risk_level}</Badge>
          <span className="text-2xl font-bold text-slate-900 dark:text-white">{fmtScore(f.predicted_risk_score)}</span>
          {f.drift_detected && <Badge tone="warning" size="sm">drift detected vs previous forecast</Badge>}
          <span className="meta-text ml-auto">{f.generated_at ? formatRelative(f.generated_at) : "time unknown"}</span>
        </div>
        <h3 className="mt-2 text-base font-bold text-slate-900 dark:text-white">
          {f.horizon_days}-day risk projection
        </h3>
        <p className="meta-text mt-1">{SCORE_BANDS_NOTE}</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="meta-text">Method</dt>
            <dd className="text-slate-700 dark:text-slate-200">{str(f.method) ?? "unknown"}</dd>
          </div>
          <div>
            <dt className="meta-text">Scope</dt>
            <dd className="text-slate-700 dark:text-slate-200">
              {f.document_id ? `document ${f.document_id}` : "neutral baseline"}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Forecast ID</dt>
            <dd className="break-all font-mono text-xs text-slate-600 dark:text-slate-300">{f.forecast_id}</dd>
          </div>
        </dl>
        {points.length > 0 && (
          <section aria-label="Projection chart" className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Projection ({points.length} point{points.length === 1 ? "" : "s"})
            </h4>
            <div className="mt-2 max-w-md">
              <BandChart points={points} />
            </div>
            <p className="meta-text mt-1">
              Line: projected score · band: projected lower–upper range ·{" "}
              {fmtDate(points[0].timestamp)} → {fmtDate(points[points.length - 1].timestamp)}
            </p>
          </section>
        )}
      </div>
    </Card>
  );
}

/* ─── policies tab ─────────────────────────────────────────────────── */

function PoliciesTab() {
  const qc = useQueryClient();
  const [scope, setScope] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const stats = useQuery({ queryKey: governanceKeys.stats(), queryFn: getGovernanceStats });
  const policies = useQuery({
    queryKey: governanceKeys.policies(),
    queryFn: () => getPolicies(scope ? { scope } : undefined),
  });
  const approvals = useQuery({
    queryKey: governanceKeys.approvalPolicies(),
    queryFn: getApprovalPolicies,
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updatePolicy(id, { enabled }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: governanceKeys.policies() });
      void qc.invalidateQueries({ queryKey: governanceKeys.stats() });
    },
  });

  return (
    <div className="space-y-4">
      <section aria-label="Governance overview" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : stats.isError ? (
          <div className="sm:col-span-2 lg:col-span-4">
            <ErrorState title="Governance statistics unavailable" error={stats.error} onRetry={() => void stats.refetch()} />
          </div>
        ) : (
          <>
            <Metric label="Policies" value={stats.data.total_policies.toLocaleString()} hint={`${stats.data.total_rules} rule(s) across policies`} />
            <Metric label="Decisions" value={stats.data.total_decisions.toLocaleString()} hint={`${stats.data.compliant_decisions} compliant · ${stats.data.non_compliant_decisions} non-compliant`} />
            <Metric label="Violations" value={stats.data.total_violations.toLocaleString()} hint={`${stats.data.blocking_violations} blocking`} />
            <Metric
              label="Compliance rate"
              value={formatNumber(stats.data.compliance_rate, 2)}
              hint="Backend share of compliant decisions (0–1)"
            />
          </>
        )}
      </section>

      <Card padding="none">
        <CardHeader
          title="Policies"
          description="Versioned, scoped rule sets. Only the enabled flag can be changed here."
          actions={
            <Select aria-label="Filter policies by scope" value={scope} onChange={(e) => setScope(e.target.value)} className="text-xs">
              <option value="">All scopes</option>
              {POLICY_SCOPES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
          }
        />
        <div className="card-body" aria-live="polite">
          {policies.isPending ? (
            <Skeleton lines={4} />
          ) : policies.isError ? (
            <ErrorState title="Policies unavailable" error={policies.error} onRetry={() => void policies.refetch()} />
          ) : (policies.data ?? []).length === 0 ? (
            <EmptyState title="No policies" description={scope ? "No policies in this scope." : "No governance policies are defined yet."} />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <caption className="sr-only">Governance policies with enabled state, version, and rule counts</caption>
                <THead>
                  <TR>
                    <TH scope="col">Name</TH>
                    <TH scope="col">Scope</TH>
                    <TH scope="col">State</TH>
                    <TH scope="col">Version</TH>
                    <TH scope="col">Rules</TH>
                    <TH scope="col">Updated</TH>
                    <TH scope="col"><span className="sr-only">Actions</span></TH>
                  </TR>
                </THead>
                <TBody>
                  {(policies.data ?? []).map((p) => {
                    const v = toPolicyView(p);
                    const isOpen = expanded === p.policy_id;
                    return (
                      <Fragment key={p.policy_id}>
                        <TR key={p.policy_id}>
                          <TD className="font-medium">
                            {p.name}
                            {p.description && <span className="meta-text block font-normal">{p.description}</span>}
                          </TD>
                          <TD>
                            {p.scope}
                            {p.scope_value && <span className="meta-text block">{p.scope_value}</span>}
                          </TD>
                          <TD><Badge tone={v.enabled ? "success" : "neutral"} size="sm">{v.statusText}</Badge></TD>
                          <TD>v{p.version}</TD>
                          <TD>{arr(p.rules).length}</TD>
                          <TD className="text-[10px]">{p.updated_at ? formatRelative(p.updated_at) : "—"}</TD>
                          <TD>
                            <div className="flex gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={toggle.isPending}
                                onClick={() => setExpanded(isOpen ? null : p.policy_id)}
                                aria-expanded={isOpen}
                              >
                                {isOpen ? "Hide rules" : `Rules (${arr(p.rules).length})`}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={toggle.isPending}
                                onClick={() => toggle.mutate({ id: p.policy_id, enabled: !p.enabled })}
                              >
                                {p.enabled ? "Disable" : "Enable"}
                              </Button>
                            </div>
                          </TD>
                        </TR>
                        {isOpen && (
                          <TR key={`${p.policy_id}-rules`}>
                            <TD colSpan={7}>
                              {arr<PolicyRule>(p.rules).length === 0 ? (
                                <p className="meta-text">This policy defines no rules.</p>
                              ) : (
                                <ul className="space-y-1.5">
                                  {arr<PolicyRule>(p.rules).map((r, i) => (
                                    <li key={str(r.rule_id) ?? `rule-${i}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-medium text-slate-900 dark:text-slate-100">{str(r.name) ?? "Unnamed rule"}</span>
                                        <Badge size="sm">{str(r.kind) ?? "unknown kind"}</Badge>
                                        <Badge size="sm">{str(r.action) ?? "no action"}</Badge>
                                        <Badge size="sm">severity: {str(r.severity) ?? "unknown"}</Badge>
                                        <Badge tone={r.enabled ? "success" : "neutral"} size="sm">{r.enabled ? "Enabled" : "Disabled"}</Badge>
                                      </div>
                                      {str(r.description) && <p className="meta-text mt-1">{r.description}</p>}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </TD>
                          </TR>
                        )}
                      </Fragment>
                    );
                  })}
                </TBody>
              </Table>
            </div>
          )}
          {toggle.isError && (
            <div className="mt-2">
              <ErrorState
                title="Policy update failed"
                error={toggle.error}
                onRetry={() => void qc.invalidateQueries({ queryKey: governanceKeys.policies() })}
              />
            </div>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Approval policies" description="Which roles may approve which decisions" />
        <div className="card-body" aria-live="polite">
          {approvals.isPending ? (
            <Skeleton lines={3} />
          ) : approvals.isError ? (
            <ErrorState title="Approval policies unavailable" error={approvals.error} onRetry={() => void approvals.refetch()} />
          ) : (approvals.data ?? []).length === 0 ? (
            <EmptyState title="No approval policies" description="No role-to-decision approval bindings are defined." />
          ) : (
            <ul className="space-y-2">
              {(approvals.data ?? []).map((ap) => (
                <li key={ap.policy_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{ap.name}</span>
                    <Badge tone={ap.enabled ? "success" : "neutral"} size="sm">{ap.enabled ? "Enabled" : "Disabled"}</Badge>
                    <span className="meta-text ml-auto">needs {ap.min_approvers} approver(s)</span>
                  </div>
                  <p className="meta-text mt-1">
                    Covers: {arr(ap.decision_types).join(", ") || "global"}
                    {ap.min_risk_level ? ` · from risk level ${ap.min_risk_level}` : ""} · Roles:{" "}
                    {arr(ap.required_roles).join(", ") || "none listed"}
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

/* ─── decisions tab ────────────────────────────────────────────────── */

const DECISION_PAGE_SIZE = 50;

function DecisionsTab() {
  const [typeFilter, setTypeFilter] = useState("");
  const [compliantFilter, setCompliantFilter] = useState("");
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, PolicyCheckResult>>({});

  const listQuery = useMemo(
    () => ({
      decision_type: typeFilter || undefined,
      policy_compliant: compliantFilter === "" ? undefined : compliantFilter === "true",
      page: page + 1,
      page_size: DECISION_PAGE_SIZE,
    }),
    [typeFilter, compliantFilter, page]
  );
  const decisions = useQuery({
    queryKey: governanceKeys.decisions({ decision_type: typeFilter || undefined, policy_compliant: compliantFilter === "" ? undefined : compliantFilter === "true" }),
    queryFn: () => getDecisions(listQuery),
  });

  const recheck = useMutation({
    mutationFn: recheckDecision,
    onSuccess: (result, id) => {
      // Re-checking evaluates; it does not rewrite the stored decision, so
      // only the inline result is recorded — no list invalidation needed.
      setChecks((prev) => ({ ...prev, [id]: result }));
    },
  });

  const list = decisions.data ?? [];
  const shortPage = list.length < DECISION_PAGE_SIZE;

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Decision registry"
          description="AI decisions captured with their policy verdicts"
          actions={
            <div className="flex gap-2">
              <Select aria-label="Filter decisions by type" value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(0); }} className="text-xs">
                <option value="">All types</option>
                {DECISION_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </Select>
              <Select aria-label="Filter by policy compliance" value={compliantFilter} onChange={(e) => { setCompliantFilter(e.target.value); setPage(0); }} className="text-xs">
                <option value="">Any verdict</option>
                <option value="true">Compliant</option>
                <option value="false">Non-compliant</option>
              </Select>
            </div>
          }
        />
        <div className="card-body" aria-live="polite">
          {decisions.isPending ? (
            <Skeleton lines={4} />
          ) : decisions.isError ? (
            <ErrorState title="Decisions unavailable" error={decisions.error} onRetry={() => void decisions.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No decisions recorded" description="The registry is empty for these filters. Decisions are registered by AI systems, not created here." />
          ) : (
            <>
              <ul className="space-y-2">
                {list.map((d) => {
                  const isOpen = expanded === d.decision_id;
                  const check = checks[d.decision_id];
                  const verdict = policyVerdict(d.policy_result);
                  return (
                    <li key={d.decision_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge size="sm">{d.decision_type}</Badge>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                          {d.subject_type && d.subject_id ? `${d.subject_type}:${d.subject_id}` : d.decision || "Untitled decision"}
                        </span>
                        <Badge tone="neutral" size="sm">{d.decision || "no verdict text"}</Badge>
                        {verdict === true && <Badge tone="success" size="sm">Policy compliant</Badge>}
                        {verdict === false && <Badge tone="danger" size="sm">Non-compliant</Badge>}
                        <span className="meta-text">{d.timestamp ? formatRelative(d.timestamp) : "time unknown"}</span>
                      </div>
                      <div className="meta-text mt-1">
                        Actor {d.actor || "unknown"}
                        {d.risk_level ? ` · risk ${d.risk_level}` : ""}
                        {arr(d.categories).length > 0 ? ` · ${arr(d.categories).join(", ")}` : ""}
                      </div>
                      <div className="mt-2 flex gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setExpanded(isOpen ? null : d.decision_id)} aria-expanded={isOpen}>
                          {isOpen ? "Hide detail" : "Detail"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={recheck.isPending}
                          disabled={recheck.isPending}
                          onClick={() => recheck.mutate(d.decision_id)}
                        >
                          Re-check policies
                        </Button>
                      </div>
                      {isOpen && <DecisionDetail decision={d} />}
                      {check && <CheckResultView result={check} />}
                      {recheck.isError && (
                        <div className="mt-2">
                          <ErrorState title="Policy re-check failed" error={recheck.error} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
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
    </div>
  );
}

/** policy_result may be absent (unchecked), an object, or malformed. */
function policyVerdict(v: unknown): boolean | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "object" && "policy_compliant" in (v as Record<string, unknown>)) {
    const b = (v as Record<string, unknown>).policy_compliant;
    return typeof b === "boolean" ? b : null;
  }
  return null;
}

function DecisionDetail({ decision: d }: { decision: GovernanceDecision }) {
  const verdict = policyVerdict(d.policy_result);
  const violations = arr<{ rule_name?: unknown; severity?: unknown; action?: unknown; message?: unknown }>(
    typeof d.policy_result === "object" && d.policy_result !== null
      ? (d.policy_result as { violations?: unknown }).violations
      : []
  );
  return (
    <dl className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-xs dark:border-slate-800">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div>
          <dt className="meta-text">Model</dt>
          <dd className="text-slate-700 dark:text-slate-200">{d.model_id || "unknown"}{d.model_version ? ` (${d.model_version})` : ""}</dd>
        </div>
        <div>
          <dt className="meta-text">Risk level</dt>
          <dd><Badge tone={levelTone(d.risk_level)} size="sm">{d.risk_level || "not recorded"}</Badge></dd>
        </div>
        <div>
          <dt className="meta-text">Reported confidence</dt>
          <dd className="text-slate-700 dark:text-slate-200">
            {typeof d.confidence === "number" ? formatNumber(d.confidence, 2) : "—"}
            <span className="meta-text block">as reported by the registrant</span>
          </dd>
        </div>
        <div>
          <dt className="meta-text">Approved by</dt>
          <dd className="text-slate-700 dark:text-slate-200">{arr(d.approved_by).join(", ") || "no approvals recorded"}</dd>
        </div>
      </div>
      <div>
        <dt className="meta-text">Policy verdict</dt>
        <dd className="text-slate-700 dark:text-slate-200">
          {verdict === null ? "Not checked against policies." : verdict ? "Compliant." : "Non-compliant."}{" "}
          {violations.length > 0 && `${violations.length} violation(s) listed below.`}
        </dd>
      </div>
      {violations.length > 0 && (
        <div>
          <dt className="meta-text">Violations</dt>
          <dd>
            <ul className="mt-1 space-y-1">
              {violations.map((v, i) => (
                <li key={i} className="rounded-lg border border-slate-200 px-2 py-1.5 dark:border-slate-700">
                  <span className="font-medium text-slate-800 dark:text-slate-100">{str(v.rule_name) ?? "Unnamed rule"}</span>{" "}
                  <Badge size="sm">{str(v.severity) ?? "unknown severity"}</Badge>{" "}
                  <Badge size="sm">{str(v.action) ?? "no action"}</Badge>
                  {str(v.message) && <span className="meta-text block">{str(v.message)}</span>}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      )}
      <div>
        <dt className="meta-text">Decision ID</dt>
        <dd className="break-all font-mono text-[11px] text-slate-500">{d.decision_id}</dd>
      </div>
    </dl>
  );
}

function CheckResultView({ result: r }: { result: PolicyCheckResult }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-700 dark:bg-slate-800/40" role="status">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-slate-900 dark:text-slate-100">Fresh policy check</span>
        <Badge tone={r.policy_compliant ? "success" : "danger"} size="sm">
          {r.policy_compliant ? "Compliant" : "Non-compliant"}
        </Badge>
        <span className="meta-text ml-auto">
          {r.evaluated_rules} rule(s) across {arr(r.evaluated_policies).length} polic(ies) ·{" "}
          {r.timestamp ? formatRelative(r.timestamp) : "just now"}
        </span>
      </div>
      {arr(r.violations).length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs">
          {arr<PolicyViolation>(r.violations).map((v, i) => (
            <li key={str(v.violation_id) ?? `vio-${i}`}>
              <span className="font-medium">{str(v.rule_name) ?? "Unnamed rule"}</span>{" "}
              <Badge size="sm">{str(v.severity) ?? "unknown"}</Badge>{" "}
              <Badge size="sm">{str(v.action) ?? "no action"}</Badge>
              {str(v.message) && <span className="meta-text block">{str(v.message)}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta-text mt-1">No violations in this check.</p>
      )}
      {arr(r.required_actions).length > 0 && (
        <p className="meta-text mt-1">Required: {arr(r.required_actions).join(", ")}</p>
      )}
      {str(r.notes) && <p className="meta-text mt-1">{r.notes}</p>}
    </div>
  );
}
