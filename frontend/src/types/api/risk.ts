/**
 * Forecasting (risk) contracts. Backend: app/api/v1/forecasting.py +
 * app/schemas/forecasting.py (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified: forecasts are {forecast_id, horizon_days, predicted_risk_score,
 * ...} (NOT projected_score/baseline_score/drivers/created_at); trend is a
 * SINGLE object {document_id, predicted_score, direction} (never an array);
 * POST /forecast REQUIRES valid keys {document_id?, horizon_days?,
 * confidence?, history?} — baseline_score/drivers are rejected (422).
 */
export interface HistoryPoint {
  timestamp: number;
  value: number;
}

export interface ForecastRequest {
  document_id?: string;
  horizon_days?: number;
  confidence?: number;
  history?: HistoryPoint[];
}

export interface RiskForecast {
  forecast_id: string;
  horizon_days: number;
  predicted_risk_score: number;
  predicted_risk_level: string;
  confidence: number;
  method: string;
  generated_at: number;
  document_id?: string | null;
  points: unknown[];
  series?: Record<string, unknown> | null;
  drift_detected: boolean;
}

export interface ForecastScenario {
  name: string;
  adjustments: Record<string, number>;
  predicted_score: number;
  predicted_level: string;
}

export interface RiskTrend {
  document_id: string;
  predicted_score: number;
  direction: string;
}
