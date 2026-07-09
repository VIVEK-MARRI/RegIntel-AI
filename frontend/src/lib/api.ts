import type { ApiError } from "@/types";
import { getAccessToken } from "@/lib/auth-token";

/**
 * Resolve the backend base URL. In dev, the Vite proxy forwards /api to
 * the FastAPI server so we always use a relative base.
 */
export const API_BASE = "/api/v1";

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
  const url = new URL(
    `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`,
    window.location.origin
  );
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
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
