import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Input, Select } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber, formatRelative } from "@/lib/format";
import { analyticsKeys } from "@/lib/queryKeys";
import {
  getAnalyticsHealth,
  getAnalyticsOverview,
  getCost,
  getIntelligenceMetrics,
  getLatency,
  getLeaderboard,
  getPerformance,
} from "@/services/api/analyticsApi";

/**
 * Agent-operations analytics: what the backend's in-memory agent metrics
 * actually record — invocations, success shares, latency, health states,
 * leaderboard ranks, cost estimates, and invocation breakdowns.
 *
 * Honesty rules applied throughout (see docs/ANALYTICS_ARCHITECTURE_STAGE13):
 * - Shares render as 0–1 numbers WITH their counts, never as percentages.
 * - An agent with zero invocations shows "no invocations", not 0.00 —
 *   the backend reports 0.0 for both "measured zero" and "never ran".
 * - No trend charts: the API exposes current aggregates only.
 * - No polling: counters refresh on user action.
 * - Leaderboard score = 0.6·success + 0.3·confidence + 0.1·speed (backend).
 * - Cost is an estimate at a fixed per-invocation rate (backend notes).
 */

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
function healthTone(h: string): Tone {
  switch (h) {
    case "healthy": return "success";
    case "degraded": return "warning";
    case "unhealthy": return "danger";
    case "unknown": return "neutral";
    default: return "neutral";
  }
}

/** Share display with its counts; "no invocations" when there is nothing to share. */
function ShareValue({ ok, total }: { ok: number; total: number }) {
  if (!Number.isFinite(total) || total <= 0) {
    return <span className="meta-text">no invocations</span>;
  }
  const share = ok / total;
  return (
    <span>
      {formatNumber(share, 2)}{" "}
      <span className="meta-text">
        ({formatNumber(ok)} of {formatNumber(total)})
      </span>
    </span>
  );
}

function MsValue({ ms, hasSamples }: { ms: number; hasSamples: boolean }) {
  if (!hasSamples) return <span className="meta-text">—</span>;
  return <span>{formatNumber(ms, ms < 10 ? 2 : 0)}ms</span>;
}

/** CSS distribution bar: parts sum to total; every part labelled in text. */
function DistBar({ parts }: { parts: { label: string; value: number; className: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (total <= 0) return <p className="meta-text">No recorded activity.</p>;
  return (
    <div>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
        role="img"
        aria-label={parts.map((p) => `${p.label}: ${p.value}`).join("; ")}
      >
        {parts.map((p) => (
          <div
            key={p.label}
            aria-hidden
            className={p.className}
            style={{ width: `${(p.value / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="meta-text mt-1.5 space-y-0.5">
        {parts.map((p) => (
          <li key={p.label}>
            {p.label}: {formatNumber(p.value)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AnalyticsPage() {
  const qc = useQueryClient();
  const [leaderTopN, setLeaderTopN] = useState(10);
  const [latencyAgent, setLatencyAgent] = useState("");

  const overview = useQuery({ queryKey: analyticsKeys.overview(), queryFn: getAnalyticsOverview });
  const performance = useQuery({ queryKey: analyticsKeys.performance(), queryFn: getPerformance });
  const intelligence = useQuery({ queryKey: analyticsKeys.intelligence(), queryFn: getIntelligenceMetrics });
  const health = useQuery({ queryKey: analyticsKeys.health(), queryFn: getAnalyticsHealth });
  const cost = useQuery({ queryKey: analyticsKeys.cost(), queryFn: getCost });
  const leaderboard = useQuery({
    queryKey: analyticsKeys.leaderboard(leaderTopN),
    queryFn: () => getLeaderboard(leaderTopN),
  });

  const refreshAll = () => void qc.invalidateQueries({ queryKey: analyticsKeys.all });

  const agents = performance.data ?? [];
  const agentNames = agents.map((a) => a.agent_name).sort();
  const effLatencyAgent = latencyAgent || agentNames[0] || "";

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Analytics</h1>
          <p className="page-description">
            Agent operations: invocations, success shares, latency, health, and
            cost estimates recorded by the backend.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={refreshAll}>
          Refresh analytics
        </Button>
      </header>

      {/* A — key metrics (current-state aggregates) */}
      <section aria-label="Key metrics" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {overview.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : overview.isError ? (
          <div className="col-span-2 lg:col-span-5">
            <ErrorState title="Overview unavailable" error={overview.error} onRetry={() => void overview.refetch()} />
          </div>
        ) : (
          <>
            <Metric label="Agents" value={formatNumber(overview.data.total_agents)} hint="Tracked agent names" />
            <Metric
              label="Invocations"
              value={formatNumber(overview.data.total_invocations)}
              hint="Succeeded + failed, current counters"
            />
            <Metric
              label="Success share"
              value={
                <ShareValue
                  ok={Math.round(overview.data.success_rate * overview.data.total_invocations)}
                  total={overview.data.total_invocations}
                />
              }
              hint="0–1 share with counts, not a percent"
            />
            <Metric
              label="Avg latency"
              value={<MsValue ms={overview.data.average_duration_ms} hasSamples={overview.data.total_invocations > 0} />}
              hint="Mean recorded duration"
            />
            <Metric
              label="Est. cost"
              value={cost.isPending ? "…" : cost.isError ? "—" : `${formatNumber(cost.data.cost_units, 4)} ${cost.data.currency}`}
              hint={cost.data ? cost.data.notes || "Backend estimate" : "Cost estimate"}
            />
          </>
        )}
      </section>
      <p className="meta-text -mt-2">
        {overview.data ? `Counters as of ${formatRelative(overview.data.generated_at)}. ` : ""}
        In-memory backend counters reset when the backend restarts; shares are 0–1 with counts.
      </p>

      {/* B — distributions */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="none">
          <CardHeader title="Success by agent" description="Succeeded vs failed invocations per agent" />
          <div className="card-body" aria-live="polite">
            {performance.isPending ? (
              <Skeleton lines={4} />
            ) : performance.isError ? (
              <ErrorState title="Agent activity unavailable" error={performance.error} onRetry={() => void performance.refetch()} />
            ) : agents.length === 0 ? (
              <EmptyState title="No agent activity" description="The backend has recorded no agent invocations yet." />
            ) : (
              <ul className="space-y-3">
                {agents.map((a) => (
                  <li key={a.agent_name}>
                    <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
                      <span className="truncate font-medium text-slate-900 dark:text-slate-100">{a.agent_name}</span>
                      <ShareValue ok={a.successful_invocations} total={a.total_invocations} />
                    </div>
                    <DistBar
                      parts={[
                        { label: "succeeded", value: a.successful_invocations, className: "bg-emerald-500" },
                        { label: "failed", value: a.failed_invocations, className: "bg-red-400" },
                      ]}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Ecosystem health" description="Backend health classification per agent" />
          <div className="card-body" aria-live="polite">
            {health.isPending ? (
              <Skeleton lines={4} />
            ) : health.isError ? (
              <ErrorState title="Health unavailable" error={health.error} onRetry={() => void health.refetch()} />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-slate-600 dark:text-slate-300">Overall:</span>
                  <Badge tone={healthTone(health.data.overall_health)}>{health.data.overall_health}</Badge>
                </div>
                <div className="mt-3">
                  <DistBar
                    parts={[
                      { label: "healthy", value: health.data.healthy_agents, className: "bg-emerald-500" },
                      { label: "degraded", value: health.data.degraded_agents, className: "bg-amber-400" },
                      { label: "unhealthy", value: health.data.unhealthy_agents, className: "bg-red-400" },
                      { label: "unknown", value: health.data.unknown_agents, className: "bg-slate-300 dark:bg-slate-600" },
                    ]}
                  />
                </div>
                <p className="meta-text mt-2">
                  Unknown = no invocations recorded. {health.data.notes ? `Backend note: ${health.data.notes}` : ""}
                </p>
              </>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader title="Invocation breakdowns" description="Recorded counts by mode and scenario kind" />
          <div className="card-body space-y-4" aria-live="polite">
            {intelligence.isPending ? (
              <Skeleton lines={3} />
            ) : intelligence.isError ? (
              <ErrorState title="Breakdowns unavailable" error={intelligence.error} onRetry={() => void intelligence.refetch()} />
            ) : (
              <>
                <div>
                  <h3 className="meta-text mb-1.5">By mode</h3>
                  {Object.keys(intelligence.data.by_mode ?? {}).length === 0 ? (
                    <p className="meta-text">No per-mode counts reported.</p>
                  ) : (
                    <DistBar
                      parts={Object.entries(intelligence.data.by_mode ?? {}).map(([label, value], i) => ({
                        label,
                        value: typeof value === "number" ? value : 0,
                        className: ["bg-brand-500", "bg-sky-500", "bg-violet-500", "bg-amber-500", "bg-emerald-500"][i % 5],
                      }))}
                    />
                  )}
                </div>
                <div>
                  <h3 className="meta-text mb-1.5">By scenario kind</h3>
                  {Object.keys(intelligence.data.by_scenario_kind ?? {}).length === 0 ? (
                    <p className="meta-text">No per-scenario counts reported.</p>
                  ) : (
                    <DistBar
                      parts={Object.entries(intelligence.data.by_scenario_kind ?? {}).map(([label, value], i) => ({
                        label,
                        value: typeof value === "number" ? value : 0,
                        className: ["bg-sky-500", "bg-violet-500", "bg-amber-500", "bg-emerald-500", "bg-brand-500"][i % 5],
                      }))}
                    />
                  )}
                </div>
              </>
            )}
            {!intelligence.isPending && !intelligence.isError && (
              <p className="meta-text mt-2">
                Collaborations: {formatNumber(intelligence.data?.total_collaborations ?? 0)} · Mean
                recorded confidence: {formatNumber(intelligence.data?.average_confidence ?? 0, 2)} ·
                Counters since {intelligence.data?.last_reset_at ? formatRelative(intelligence.data.last_reset_at) : "unknown"}.
              </p>
            )}
          </div>
        </Card>

        <Card padding="none">
          <CardHeader
            title="Leaderboard"
            description="Rank by composite score: 0.6·success + 0.3·confidence + 0.1·speed (backend)"
            actions={
              <Field label="Top N" id="leader-topn">
                <Input
                  id="leader-topn"
                  type="number"
                  min={1}
                  max={50}
                  value={leaderTopN}
                  onChange={(e) => setLeaderTopN(Math.min(50, Math.max(1, Number(e.target.value) || 10)))}
                  className="w-20 text-xs"
                />
              </Field>
            }
          />
          <div className="card-body" aria-live="polite">
            {leaderboard.isPending ? (
              <Skeleton lines={4} />
            ) : leaderboard.isError ? (
              <ErrorState title="Leaderboard unavailable" error={leaderboard.error} onRetry={() => void leaderboard.refetch()} />
            ) : (leaderboard.data ?? []).length === 0 ? (
              <EmptyState title="No ranked agents" description="Nothing to rank yet." />
            ) : (
              <ol className="space-y-2">
                {(leaderboard.data ?? []).map((e) => (
                  <li key={e.agent_name} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-500 text-[10px] font-bold text-white" aria-label={`Rank ${e.rank}`}>
                      {e.rank}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium text-slate-900 dark:text-slate-100">{e.agent_name}</span>
                    <span className="font-semibold text-slate-900 dark:text-slate-100">score {formatNumber(e.score, 2)}</span>
                    <ShareValue ok={Math.round(e.success_rate * e.total_invocations)} total={e.total_invocations} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </Card>
      </div>

      {/* latency explorer */}
      <Card padding="none">
        <CardHeader
          title="Latency explorer"
          description="Recorded duration distribution for one agent (milliseconds)"
          actions={
            <Field label="Agent" id="latency-agent">
              <Select
                id="latency-agent"
                value={effLatencyAgent}
                onChange={(e) => setLatencyAgent(e.target.value)}
                className="text-xs"
              >
                {agentNames.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </Select>
            </Field>
          }
        />
        <div className="card-body" aria-live="polite">
          {agents.length === 0 ? (
            <EmptyState title="No agents" description="Latency needs at least one tracked agent." />
          ) : (
            <LatencyDetail agentName={effLatencyAgent} />
          )}
        </div>
      </Card>

      {/* C — time series: honestly absent */}
      <Card padding="md">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Trends over time</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          Historical trend data is not available from the current analytics API:
          every endpoint above exposes current aggregates, not timestamped
          series. No trend chart is shown rather than an invented one.
        </p>
      </Card>

      {/* D — analytical table */}
      <Card padding="none">
        <CardHeader title="Agent performance" description="Raw per-agent numbers behind the charts" />
        <div className="card-body" aria-live="polite">
          {performance.isPending ? (
            <Skeleton lines={5} />
          ) : performance.isError ? (
            <ErrorState title="Performance table unavailable" error={performance.error} onRetry={() => void performance.refetch()} />
          ) : agents.length === 0 ? (
            <EmptyState title="No performance data" description="No agent executions have been recorded." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <caption className="sr-only">Per-agent invocations, success share, latency, and health</caption>
                <THead>
                  <TR>
                    <TH scope="col">Agent</TH>
                    <TH scope="col">Invocations</TH>
                    <TH scope="col">Succeeded</TH>
                    <TH scope="col">Failed</TH>
                    <TH scope="col">Share</TH>
                    <TH scope="col">Avg ms</TH>
                    <TH scope="col">P95 ms</TH>
                    <TH scope="col">Health</TH>
                    <TH scope="col">Last invocation</TH>
                  </TR>
                </THead>
                <TBody>
                  {agents.map((a) => (
                    <TR key={a.agent_name}>
                      <TD className="font-medium">{a.agent_name}</TD>
                      <TD>{formatNumber(a.total_invocations)}</TD>
                      <TD>{formatNumber(a.successful_invocations)}</TD>
                      <TD>{formatNumber(a.failed_invocations)}</TD>
                      <TD><ShareValue ok={a.successful_invocations} total={a.total_invocations} /></TD>
                      <TD><MsValue ms={a.average_duration_ms} hasSamples={a.total_invocations > 0} /></TD>
                      <TD><MsValue ms={a.p95_duration_ms} hasSamples={a.total_invocations > 0} /></TD>
                      <TD><Badge tone={healthTone(a.health)} size="sm">{a.health}</Badge></TD>
                      <TD className="whitespace-nowrap text-[11px]">
                        {a.last_invocation_at ? formatRelative(a.last_invocation_at) : "never"}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
          {agents.some((a) => a.last_error) && (
            <ul className="meta-text mt-2 space-y-1">
              {agents
                .filter((a) => a.last_error)
                .map((a) => (
                  <li key={a.agent_name} className="truncate" title={a.last_error}>
                    Last error ({a.agent_name}): {a.last_error}
                  </li>
                ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}

function LatencyDetail({ agentName }: { agentName: string }) {
  const latency = useQuery({
    queryKey: analyticsKeys.latency(agentName || "none"),
    queryFn: () => getLatency(agentName),
    enabled: agentName !== "",
  });

  if (!agentName) return <p className="meta-text">Select an agent.</p>;
  if (latency.isPending) return <Skeleton lines={3} />;
  if (latency.isError) {
    return <ErrorState title="Latency unavailable" error={latency.error} onRetry={() => void latency.refetch()} />;
  }
  const d = latency.data;
  if (d.count <= 0) {
    return <EmptyState title="No latency samples" description={`The backend recorded no durations for ${agentName}.`} />;
  }
  const rows: [string, number][] = [
    ["Samples", d.count],
    ["Average", d.average_ms],
    ["Min", d.min_ms],
    ["P50", d.p50_ms],
    ["P90", d.p90_ms],
    ["P95", d.p95_ms],
    ["P99", d.p99_ms],
    ["Max", d.max_ms],
  ];
  const max = Math.max(d.max_ms, 1);
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div
        role="img"
        aria-label={`Latency for ${agentName}: average ${d.average_ms}ms, p95 ${d.p95_ms}ms, max ${d.max_ms}ms over ${d.count} samples.`}
      >
        {rows.slice(1).map(([label, v]) => (
          <div key={label} className="mb-1.5 flex items-center gap-2 text-xs">
            <span className="w-16 shrink-0 text-slate-500 dark:text-slate-400">{label}</span>
            <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div aria-hidden className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, (v / max) * 100)}%` }} />
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-slate-700 dark:text-slate-200">
              {formatNumber(v, v < 10 ? 2 : 0)}ms
            </span>
          </div>
        ))}
      </div>
      <Table>
        <caption className="sr-only">Latency statistics in milliseconds with sample count</caption>
        <THead>
          <TR>
            <TH scope="col">Statistic</TH>
            <TH scope="col">Milliseconds</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map(([label, v]) => (
            <TR key={label}>
              <TD>{label}</TD>
              <TD className="font-mono">{label === "Samples" ? formatNumber(v) : `${formatNumber(v, v < 10 ? 2 : 0)}ms`}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
