import { API_BASE_URL, API_PREFIX } from "@/lib/config";
import { ApiClientError } from "@/lib/errors";

/**
 * Canonical HTTP client. EVERY service goes through here (including health
 * and auth); there is exactly ONE error model (ApiClientError).
 *
 * Responsibility boundary (Stage 03 owns auth internals):
 * - THIS client owns: URL building, headers, timeouts, cancellation,
 *   401 detection + single-flight refresh orchestration + one retry.
 * - THE AUTH SYSTEM owns: tokens, the refresh operation, session, logout.
 *   It plugs in via setAuthHandler(); the client never stores credentials.
 */

export const DEFAULT_TIMEOUT_MS = 30_000;
/** Long-running operations (copilot/research/forecast/agent-execute). */
export const LONG_TIMEOUT_MS = 120_000;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Caller cancellation (e.g. unmount, query cancel). Combined with timeout. */
  signal?: AbortSignal;
  /** Per-request timeout override. 0 disables the timeout. */
  timeoutMs?: number;
  headers?: Record<string, string>;
  /** When true, returns ReadableStream<Uint8Array> instead of parsed JSON. */
  stream?: boolean;
}

export interface AuthHandler {
  getAccessToken: () => string | null;
  /**
   * Perform ONE token rotation. Must be idempotent-safe to call rarely;
   * the client guarantees at most one in-flight call (single-flight).
   * Resolve true when a fresh access token is available.
   */
  refreshAccessToken: () => Promise<boolean>;
  /** Session is dead (refresh failed/rejected): clear local session state. */
  onAuthFailure: () => void;
}

let authHandler: AuthHandler | null = null;

export function setAuthHandler(handler: AuthHandler | null): void {
  authHandler = handler;
}

/** Auth endpoints must never trigger refresh (no recursion, no loops). */
const AUTH_EXEMPT_PREFIXES = [
  "/security/auth/login",
  "/security/auth/refresh",
  "/security/auth/signup",
];

function isAuthExempt(path: string): boolean {
  return AUTH_EXEMPT_PREFIXES.some((p) => path.startsWith(p));
}

/** Encode a single path segment (IDs, names). Never interpolate raw IDs. */
export function encodePathSegment(value: string | number): string {
  return encodeURIComponent(String(value));
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"]
): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const full = `${API_BASE_URL}${API_PREFIX}${normalized}`;
  const url = API_BASE_URL
    ? new URL(full)
    : new URL(full, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  // Same-origin: keep relative (Vite proxy / reverse proxy). Cross-origin:
  // absolute URL (Render static + public API).
  return API_BASE_URL ? url.toString() : url.pathname + url.search;
}

/** Root-level URL builder (health lives at /health/*, not /api/v1). */
export function buildRootUrl(
  path: string,
  query?: RequestOptions["query"]
): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const full = `${API_BASE_URL}${normalized}`;
  const url = API_BASE_URL
    ? new URL(full)
    : new URL(full, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  return API_BASE_URL ? url.toString() : url.pathname + url.search;
}

function parseBody(text: string): unknown {
  if (text.length === 0) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiClientError(
      200,
      "Invalid JSON response from server",
      text.slice(0, 500),
      "invalid-response"
    );
  }
}

function toHttpError(status: number, parsed: unknown, statusText: string): ApiClientError {
  const detail =
    parsed !== null && typeof parsed === "object" && "detail" in parsed
      ? (parsed as { detail?: unknown }).detail
      : parsed;
  const message =
    typeof detail === "string" && detail
      ? detail
      : Array.isArray(detail)
        ? detail
            .map((d) =>
              typeof d === "string" ? d : JSON.stringify(d)
            )
            .join("; ")
        : statusText || `Request failed with status ${status}`;
  return new ApiClientError(status, message, detail ?? parsed);
}

// Single-flight refresh: concurrent 401s queue behind ONE rotation.
let refreshPromise: Promise<boolean> | null = null;

function refreshOnce(): Promise<boolean> {
  if (!authHandler) return Promise.resolve(false);
  if (!refreshPromise) {
    refreshPromise = authHandler
      .refreshAccessToken()
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

interface InternalOptions extends RequestOptions {
  _retried?: boolean;
  _root?: boolean;
}

async function doFetch(
  url: string,
  init: RequestInit,
  stream: boolean | undefined
): Promise<{ res: Response; parsed: unknown }> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // Distinguish caller-cancel vs our timeout via the reason we set.
      const reason = (init.signal as AbortSignal | undefined)?.reason;
      if (reason === "timeout") {
        throw new ApiClientError(0, "Request timed out", undefined, "timeout");
      }
      throw new ApiClientError(0, "Request was cancelled", undefined, "aborted");
    }
    throw new ApiClientError(
      0,
      "Network error: unable to reach the server",
      undefined,
      "network"
    );
  }
  if (stream) {
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw toHttpError(res.status, text, res.statusText);
    }
    return { res, parsed: res.body };
  }
  const text = await res.text();
  return { res, parsed: parseBody(text) };
}

export async function request<T = unknown>(
  path: string,
  options: RequestOptions & { _root?: boolean } = {}
): Promise<T> {
  const {
    method = "GET",
    body,
    query,
    signal: userSignal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    headers = {},
    stream,
    _root = false,
    _retried = false,
  } = options as InternalOptions;

  const token = authHandler?.getAccessToken() ?? null;
  const initHeaders: Record<string, string> = { Accept: "application/json" };
  if (token) initHeaders["Authorization"] = `Bearer ${token}`;
  for (const [k, v] of Object.entries(headers)) initHeaders[k] = v;

  const init: RequestInit = { method, headers: initHeaders };
  if (body !== undefined && body !== null) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      initHeaders["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }

  const url = _root ? buildRootUrl(path, query) : buildUrl(path, query);

  // Combine caller signal + timeout into one AbortSignal.
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const onUserAbort = () => controller.abort(userSignal?.reason ?? "cancelled");
  if (userSignal) {
    if (userSignal.aborted) controller.abort(userSignal.reason ?? "cancelled");
    else userSignal.addEventListener("abort", onUserAbort, { once: true });
  }
  if (timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      try {
        controller.abort("timeout");
      } catch {
        /* noop */
      }
    }, timeoutMs);
    // Avoid keeping Node/Vitest processes alive on the timer alone.
    const t = timeoutId as unknown as { unref?: () => void };
    if (typeof t.unref === "function") t.unref();
  }
  init.signal = controller.signal;

  try {
    const { res, parsed } = await doFetch(url, init, stream);
    if (stream) return parsed as T;

    if (res.status === 401 && authHandler && !_retried && !isAuthExempt(path)) {
      const refreshed = await refreshOnce();
      if (refreshed) {
        return request<T>(path, { ...options, _retried: true } as RequestOptions);
      }
      try {
        authHandler.onAuthFailure();
      } catch {
        /* session cleanup must never break error propagation */
      }
    }

    if (!res.ok) throw toHttpError(res.status, parsed, res.statusText);
    return parsed as T;
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    userSignal?.removeEventListener("abort", onUserAbort);
  }
}

/** Root-level request (health endpoints live outside /api/v1). */
export function requestRoot<T = unknown>(
  path: string,
  options?: RequestOptions
): Promise<T> {
  return request<T>(path, { ...options, _root: true });
}

export const api = {
  get: <T = unknown>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "POST", body }),
  put: <T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "PUT", body }),
  patch: <T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  del: <T = unknown>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
