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
import { useQuery, useMutation } from "@tanstack/react-query";
import { getRiskForecasts, getRiskScenarios, forecastRisk } from "@/services/api/riskApi";
import { useToast } from "@/providers/ToastProvider";
import { formatNumber } from "@/lib/format";

export function RiskPage() {
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
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Risk</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Risk assessment, impact distribution, and risk trends.</p>
      </header>

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
                      <span className="text-slate-500 dark:text-slate-400">{formatNumber(f.projected_score)} / 100</span>
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
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{s.description}</p>
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}
