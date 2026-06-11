import { api } from "@/lib/api";
import type { RiskForecast, RiskScenario, RiskProjection } from "@/types";

export async function getRiskForecasts(): Promise<RiskForecast[]> {
  return api.get("/forecasting/forecasts");
}

export async function getRiskScenarios(): Promise<RiskScenario[]> {
  return api.get("/forecasting/scenarios");
}

export async function getRiskTrend(documentId: string): Promise<RiskProjection[]> {
  return api.get(`/forecasting/trend/${encodeURIComponent(documentId)}`);
}

export async function forecastRisk(payload: {
  horizon_days: number;
  baseline_score?: number;
  drivers?: string[];
}): Promise<RiskForecast> {
  return api.post("/forecasting/forecast", payload);
}
