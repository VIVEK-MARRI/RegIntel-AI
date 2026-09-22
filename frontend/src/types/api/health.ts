/**
 * Health contracts. Backend: app/api/v1/health.py (prefix /health, mounted
 * at ROOT — not /api/v1). /health/live is public; /health/ready may 401 in
 * production (client falls back to /live) and may 503 when UNHEALTHY.
 *
 * Verified: /ready returns HealthChecker.report.to_dict() = {status,
 * checks: {name: {...}}} — an OBJECT map, not an array. Never .map() it.
 */
export interface HealthCheckDetail {
  status: string;
  latency_ms?: number;
  message?: string;
  details?: Record<string, unknown>;
}

export interface ReadyReport {
  status: string;
  checks: Record<string, HealthCheckDetail>;
  [key: string]: unknown;
}

export interface LiveReport {
  status: string;
  [key: string]: unknown;
}

/** UI-level rollup derived by HealthProvider (not a backend shape). */
export type HealthLevel = "healthy" | "degraded" | "unhealthy";

export interface HealthState {
  level: HealthLevel;
  version?: string;
  uptimeSeconds?: number;
}
