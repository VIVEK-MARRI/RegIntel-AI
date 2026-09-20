import type { ApiError } from "@/types";
import { getAccessToken } from "@/lib/auth-token";

/**
 * Resolve the backend base URL.
 *
 * - Local dev: the Vite proxy forwards /api to FastAPI, so a relative base
 *   works and no env var is needed.
 * - Render (static CDN frontend + public API web service): the browser must
 *   call the backend's public URL directly, baked in at build time via
 *   VITE_API_BASE_URL (see render.yaml). Same-origin stays relative.
 */
export const BACKEND_BASE = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

export const API_BASE = `${BACKEND_BASE}/api/v1`;

export class ApiClientError extends Error implements ApiError {
  status: number;
  detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** When true, returns a ReadableStream<Uint8Array> instead of parsed JSON. */
  stream?: boolean;
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"]
): string {
  const full = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  const url = BACKEND_BASE
    ? new URL(full)
    : new URL(full, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  // Same-origin: keep relative (works behind Vite proxy / any reverse proxy).
  // Cross-origin (Render): return the absolute URL.
  return BACKEND_BASE ? url.toString() : url.pathname + url.search;
}

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { method = "GET", body, query, signal, headers = {}, stream } = options;

  const token = getAccessToken();
  const initHeaders: Record<string, string> = {
    Accept: "application/json",
  };
  if (token) {
    initHeaders["Authorization"] = `Bearer ${token}`;
  }
  for (const [k, v] of Object.entries(headers)) {
    initHeaders[k] = v;
  }

  const init: RequestInit = {
    method,
    signal,
    headers: initHeaders,
  };

  if (body !== undefined && body !== null) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      (init.headers as Record<string, string>)["Content-Type"] =
        "application/json";
      init.body = JSON.stringify(body);
    }
  }

  const url = buildUrl(path, query);
  const res = await fetch(url, init);

  if (stream) {
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new ApiClientError(res.status, text || res.statusText);
    }
    return res.body as unknown as T;
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!res.ok) {
    const detail = (parsed as { detail?: unknown })?.detail ?? parsed;
    const message =
      typeof detail === "string"
        ? detail
        : res.statusText || `Request failed with status ${res.status}`;
    throw new ApiClientError(res.status, message, detail);
  }

  return parsed as T;
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
