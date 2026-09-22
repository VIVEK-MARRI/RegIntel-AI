import { LONG_TIMEOUT_MS, api, encodePathSegment } from "@/lib/api";
import type {
  ForecastRequest,
  ForecastScenario,
  RiskForecast,
  RiskTrend,
} from "@/types/api/risk";

export async function getRiskForecasts(): Promise<RiskForecast[]> {
  // GET /forecasting/forecasts returns a BARE ARRAY.
  return api.get<RiskForecast[]>("/forecasting/forecasts");
}

export async function getRiskScenarios(): Promise<ForecastScenario[]> {
  return api.get<ForecastScenario[]>("/forecasting/scenarios");
}

export async function getRiskTrend(documentId: string): Promise<RiskTrend> {
  // GET /forecasting/trend/:id returns a SINGLE OBJECT (never an array).
  return api.get<RiskTrend>(
    `/forecasting/trend/${encodePathSegment(documentId)}`
  );
}

/**
 * Backend ForecastRequest accepts ONLY document_id / horizon_days /
 * confidence / history (extra=forbid). Never send baseline_score or
 * drivers — the backend rejects them with 422.
 */
export async function forecastRisk(payload: ForecastRequest): Promise<RiskForecast> {
  return api.post<RiskForecast>("/forecasting/forecast", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}
