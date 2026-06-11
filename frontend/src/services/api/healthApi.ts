export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  version?: string;
  uptime_seconds?: number;
  components?: Record<string, { status: string; latency_ms?: number }>;
}

/** The health endpoint lives at root level (/health/*), not under /api/v1. */
export async function getHealth(): Promise<HealthStatus> {
  const res = await fetch("/health/ready", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || res.statusText);
  }
  return res.json();
}
