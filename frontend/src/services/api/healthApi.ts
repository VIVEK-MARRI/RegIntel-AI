import { requestRoot } from "@/lib/api";
import type { HealthState, LiveReport, ReadyReport } from "@/types/api/health";

/**
 * Health lives at the ROOT (/health/*), not under /api/v1.
 * /health/live is public; /health/ready may 401 in production — callers
 * fall back to /live. Response `checks` is an OBJECT map, never an array.
 */
export async function getReadyReport(): Promise<ReadyReport> {
  return requestRoot<ReadyReport>("/health/ready");
}

export async function getLiveReport(): Promise<LiveReport> {
  return requestRoot<LiveReport>("/health/live");
}

/** Roll the backend reports up to one UI-level state. Never throws. */
export async function getHealth(): Promise<HealthState> {
  try {
    const ready = await getReadyReport();
    const level =
      ready.status === "healthy" || ready.status === "ok"
        ? "healthy"
        : ready.status === "degraded"
          ? "degraded"
          : "unhealthy";
    return { level };
  } catch {
    try {
      await getLiveReport();
      return { level: "healthy" };
    } catch {
      return { level: "unhealthy" };
    }
  }
}
