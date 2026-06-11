import { useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Field, Input } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useForecastRisk, useRiskForecasts, useRiskScenarios } from "@/hooks/api";
import { useDemoQuery } from "@/hooks/useDemoFallback";
import { demoRiskForecasts, demoRiskScenarios } from "@/lib/demo";
import { useToast } from "@/providers/ToastProvider";
import { formatPercent, formatRelative } from "@/lib/format";

export function RiskPage() {
  const forecasts = useDemoQuery("Risk", demoRiskForecasts, useRiskForecasts);
  const scenarios = useDemoQuery("Risk", demoRiskScenarios, useRiskScenarios);
  const forecast = useForecastRisk();
  const toast = useToast();
  const [horizon, setHorizon] = useState(30);
  const [baseline, setBaseline] = useState(60);

  async function handleRun() {
    try {
      const result = await forecast.mutateAsync({
        horizon_days: horizon,
        baseline_score: baseline,
      });
      toast.push({
        title: "Forecast generated",
        description: `Projected score: ${result.projected_score}`,
        tone: "success",
      });
    } catch (err) {
      toast.push({
        title: "Forecast failed",
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
            Risk Workspace
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Run forward-looking risk forecasts and explore scenarios.
          </p>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Horizon (days)" id="risk-horizon">
              <Input
                id="risk-horizon"
                type="number"
                min={1}
                max={365}
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
              />
            </Field>
            <Field label="Baseline score" id="risk-baseline">
              <Input
                id="risk-baseline"
                type="number"
                min={0}
                max={100}
                value={baseline}
                onChange={(e) => setBaseline(Number(e.target.value))}
              />
            </Field>
            <div className="flex items-end">
              <Button
                variant="primary"
                onClick={handleRun}
                loading={forecast.isPending}
              >
                Generate forecast
              </Button>
            </div>
          </div>
        </Card>

        <Card padding="none">
          <CardHeader
            title="Recent forecasts"
            description="Stored risk projections"
          />
          <div className="card-body">
            {forecasts.isLoading ? (
              <Skeleton lines={4} />
            ) : forecasts.isError ? (
              <ErrorState
                error={forecasts.error}
                onRetry={() => forecasts.refetch()}
              />
            ) : !forecasts.data || forecasts.data.length === 0 ? (
              <EmptyState
                title="No forecasts yet"
                description="Generate a forecast above to populate this list."
              />
            ) : (
              <ul className="space-y-3">
                {forecasts.data.map((f) => {
                  const trend = f.projected_score - f.baseline_score;
                  return (
                    <li
                      key={f.forecast_id}
                      className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {f.horizon_days}-day horizon
                        </span>
                        <Badge
                          tone={trend > 0 ? "danger" : "success"}
                          size="sm"
                        >
                          {trend > 0 ? "▲" : "▼"} {Math.abs(trend).toFixed(0)}
                        </Badge>
                        <Badge tone="brand" size="sm">
                          {formatPercent(f.confidence)} conf
                        </Badge>
                        <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                          {formatRelative(f.created_at)}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-3">
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                            Baseline
                          </p>
                          <ProgressBar
                            value={f.baseline_score}
                            max={100}
                            tone="warning"
                            className="mt-1"
                          />
                          <p className="mt-1 font-mono text-xs">{f.baseline_score}/100</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                            Projected
                          </p>
                          <ProgressBar
                            value={f.projected_score}
                            max={100}
                            tone={f.projected_score > 75 ? "danger" : "brand"}
                            className="mt-1"
                          />
                          <p className="mt-1 font-mono text-xs">{f.projected_score}/100</p>
                        </div>
                      </div>
                      {f.drivers?.length ? (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {f.drivers.slice(0, 4).map((d, i) => (
                            <Badge key={i} tone="neutral" size="sm">
                              {d}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card padding="none">
          <CardHeader title="Scenarios" description="What-if risk scenarios" />
          <div className="card-body">
            {scenarios.isLoading ? (
              <Skeleton lines={3} />
            ) : !scenarios.data || scenarios.data.length === 0 ? (
              <EmptyState title="No scenarios" />
            ) : (
              <ul className="space-y-2">
                {scenarios.data.map((s) => (
                  <li
                    key={s.scenario_id}
                    className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
                  >
                    <div className="flex items-center gap-2">
                      <Badge
                        tone={
                          s.impact === "critical"
                            ? "danger"
                            : s.impact === "high"
                              ? "warning"
                              : "info"
                        }
                        size="sm"
                      >
                        {s.impact}
                      </Badge>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {s.name}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                      {s.description}
                    </p>
                    <div className="mt-2">
                      <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
                        Probability
                      </p>
                      <ProgressBar
                        value={s.probability * 100}
                        max={100}
                        tone={s.probability > 0.5 ? "danger" : "brand"}
                        className="mt-1"
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </aside>
    </div>
  );
}
