/**
 * The ONE canonical error model for the frontend.
 *
 * Every service throws this (never raw Error, never a second error class),
 * so pages can rely on `status` + `message` + `detail` without parsing.
 * Backend errors arrive as `{"detail": str | [...]}` (HTTPException / 422);
 * network/timeout/abort conditions use status 0 with a machine `code`.
 */
export type ApiErrorCode =
  | "http"
  | "timeout"
  | "aborted"
  | "network"
  | "invalid-response";

export class ApiClientError extends Error {
  readonly status: number;
  readonly detail?: unknown;
  readonly code: ApiErrorCode;

  constructor(
    status: number,
    message: string,
    detail?: unknown,
    code: ApiErrorCode = "http"
  ) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

export function isApiError(err: unknown): err is ApiClientError {
  return err instanceof ApiClientError;
}

/** Human-safe message for any thrown value. Never leaks objects. */
export function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiClientError) return err.message;
  if (err instanceof Error) return err.message || fallback;
  if (typeof err === "string" && err) return err;
  return fallback;
}
