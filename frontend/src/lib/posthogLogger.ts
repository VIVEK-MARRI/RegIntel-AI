import posthog, { isPostHogEnabled } from "@/lib/posthog";
import type { ApiErrorCode } from "@/lib/errors";

/**
 * Dedicated PostHog log emitter. Only the purpose-written records in this
 * module are exported; existing browser console output remains local.
 */
const posthogLog = posthog.logger;

export function logApplicationStarted(): void {
  if (!isPostHogEnabled) return;

  posthogLog.info("frontend application started", {
    event: "frontend.application_started",
  });
}

export function logApiRequestFailed({
  method,
  requestScope,
  status,
  errorCode,
}: {
  method: string;
  requestScope: "api" | "root";
  status: number;
  errorCode: ApiErrorCode | "unknown";
}): void {
  if (!isPostHogEnabled) return;

  posthogLog.warn("frontend API request failed", {
    event: "frontend.api_request_failed",
    method,
    request_scope: requestScope,
    status,
    error_code: errorCode,
  });
}
