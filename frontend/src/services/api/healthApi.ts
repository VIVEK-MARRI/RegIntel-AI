export interface HealthComponent {
  name?: string;
  status: string;
  latency_ms?: number;
  message?: string;
  details?: Record<string, unknown>;
}

export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  version?: string;
  uptime_seconds?: number;
  // /health/ready returns components as an ARRAY; /health/live has none.
  components?: HealthComponent[];
}

import { getAccessToken } from "@/lib/auth-token";

/** The health endpoint lives at root level (/health/*), not under /api/v1. */
export async function getHealth(): Promise<HealthStatus> {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  const headers: Record<string, string> = { Accept: "application/json" };
  // /health/ready requires a Bearer token in production (it can echo
  // backend diagnostics). Attach it when the user is signed in.
  const token = getAccessToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${base}/health/ready`, { headers });
  if (res.status === 401) {
    // Anonymous (or logged-out) callers fall back to the public liveness
    // probe so the UI still renders instead of erroring out.
    const live = await fetch(`${base}/health/live`, {
      headers: { Accept: "application/json" },
    });
    if (!live.ok) {
      throw new Error((await live.text().catch(() => "")) || live.statusText);
    }
    return { status: "healthy" };
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || res.statusText);
  }
  return res.json();
}
