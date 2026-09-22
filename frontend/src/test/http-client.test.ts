/**
 * Foundation tests for the canonical HTTP client (lib/api.ts).
 * Uses a directly stubbed fetch for deterministic control over timing,
 * aborts, and call counts. MSW-based contract tests live in
 * api-contracts.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  encodePathSegment,
  request,
  setAuthHandler,
} from "@/lib/api";
import { ApiClientError } from "@/lib/errors";
import { setAccessToken } from "@/lib/auth-token";

function jsonResponse(body: unknown, status = 200, statusText = "OK"): Response {
  return new Response(
    body === undefined || body === null || body === "" ? "" : JSON.stringify(body),
    { status, statusText, headers: { "Content-Type": "application/json" } }
  );
}

let calls: Array<{ url: string; init: RequestInit }> = [];

function stubFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return handler(url, init);
    })
  );
}

beforeEach(() => {
  setAuthHandler(null);
  setAccessToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthHandler(null);
  setAccessToken(null);
});

describe("request basics", () => {
  it("GET builds a same-origin relative URL with query params", async () => {
    stubFetch(() => jsonResponse({ items: [] }));
    await api.get("/documents", { query: { source: "RBI", skip: 0 } });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/v1/documents?source=RBI&skip=0");
    expect(calls[0].init.method).toBe("GET");
    expect((calls[0].init.headers as Record<string, string>)["Accept"]).toBe(
      "application/json"
    );
  });

  it("POST sends JSON with Content-Type", async () => {
    stubFetch(() => jsonResponse({ ok: true }));
    await api.post("/research/run", { query: "q", max_steps: 3 });
    expect(calls[0].init.method).toBe("POST");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      query: "q",
      max_steps: 3,
    });
  });

  it("POST sends FormData without a JSON Content-Type", async () => {
    stubFetch(() => jsonResponse({ document_id: "d" }, 201));
    const form = new FormData();
    form.append("file", new File(["x"], "a.pdf"));
    await api.post("/documents/upload", form);
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(calls[0].init.body).toBe(form);
  });

  it("returns null for empty 2xx bodies", async () => {
    stubFetch(() => new Response(null, { status: 204 }));
    await expect(api.get("/anything")).resolves.toBeNull();
  });

  it("attaches Bearer token when the auth handler provides one", async () => {
    setAuthHandler({
      getAccessToken: () => "tok-123",
      refreshAccessToken: async () => false,
      onAuthFailure: () => {},
    });
    stubFetch(() => jsonResponse({}));
    await api.get("/documents");
    expect((calls[0].init.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer tok-123"
    );
  });

  it("sends no Authorization header without a token", async () => {
    setAuthHandler({
      getAccessToken: () => null,
      refreshAccessToken: async () => false,
      onAuthFailure: () => {},
    });
    stubFetch(() => jsonResponse({}));
    await api.get("/documents");
    expect(
      (calls[0].init.headers as Record<string, string>)["Authorization"]
    ).toBeUndefined();
  });
});

describe("error model", () => {
  it("parses string detail into message", async () => {
    stubFetch(() => jsonResponse({ detail: "boom happened" }, 400, "Bad Request"));
    const err: unknown = await api.get("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).status).toBe(400);
    expect((err as ApiClientError).message).toBe("boom happened");
    expect((err as ApiClientError).detail).toBe("boom happened");
  });

  it("joins array detail (422 validation) into message", async () => {
    stubFetch(() =>
      jsonResponse({ detail: [{ loc: ["scope"], msg: "extra forbidden" }] }, 422, "Unprocessable")
    );
    const err: unknown = await api.get("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).status).toBe(422);
    expect((err as ApiClientError).message).toContain("extra forbidden");
  });

  it("throws invalid-response for non-JSON 2xx bodies", async () => {
    stubFetch(() => new Response("<html>nope</html>", { status: 200 }));
    const err: unknown = await api.get("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).code).toBe("invalid-response");
  });

  it("maps fetch rejection to a network error", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const err: unknown = await api.get("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).code).toBe("network");
    expect((err as ApiClientError).status).toBe(0);
  });
});

describe("timeout and cancellation", () => {
  /** A hung server that faithfully rejects when the client aborts. */
  function stubHungServer() {
    stubFetch(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => {
            reject(new DOMException("This operation was aborted", "AbortError"));
          });
        })
    );
  }

  it("aborts with a timeout error when the server is slow", async () => {
    stubHungServer();
    const err: unknown = await api.get("/slow", { timeoutMs: 40 }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).code).toBe("timeout");
  });

  it("maps caller AbortController to an aborted error", async () => {
    stubHungServer();
    const controller = new AbortController();
    const pending = api.get("/slow", { signal: controller.signal, timeoutMs: 0 });
    controller.abort();
    const err: unknown = await pending.catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).code).toBe("aborted");
  });
});

describe("401 recovery (single-flight, retry-once)", () => {
  it("refreshes once and retries the original request with the new token", async () => {
    let token: string | null = "stale";
    let refreshCalls = 0;
    setAuthHandler({
      getAccessToken: () => token,
      refreshAccessToken: async () => {
        refreshCalls += 1;
        token = "fresh";
        return true;
      },
      onAuthFailure: () => {},
    });
    stubFetch((_url, init) => {
      const auth = (init.headers as Record<string, string>)["Authorization"];
      if (auth === "Bearer fresh") return jsonResponse({ ok: true });
      return jsonResponse({ detail: "expired" }, 401, "Unauthorized");
    });
    const res = await api.get<{ ok: boolean }>("/documents");
    expect(res).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
    expect(calls).toHaveLength(2);
    expect((calls[1].init.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer fresh"
    );
  });

  it("queues concurrent 401s behind ONE refresh", async () => {
    let token: string | null = "stale";
    let refreshCalls = 0;
    const onFailure = vi.fn();
    setAuthHandler({
      getAccessToken: () => token,
      refreshAccessToken: async () => {
        refreshCalls += 1;
        await new Promise((r) => setTimeout(r, 20));
        token = "fresh";
        return true;
      },
      onAuthFailure: onFailure,
    });
    stubFetch((_url, init) => {
      const auth = (init.headers as Record<string, string>)["Authorization"];
      if (auth === "Bearer fresh") return jsonResponse({ ok: true });
      return jsonResponse({ detail: "expired" }, 401, "Unauthorized");
    });
    const [a, b, c] = await Promise.all([
      api.get("/one"),
      api.get("/two"),
      api.get("/three"),
    ]);
    expect([a, b, c]).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("rejects queued requests and calls onAuthFailure when refresh fails", async () => {
    const onFailure = vi.fn();
    setAuthHandler({
      getAccessToken: () => "stale",
      refreshAccessToken: async () => false,
      onAuthFailure: onFailure,
    });
    stubFetch(() => jsonResponse({ detail: "expired" }, 401, "Unauthorized"));
    const err: unknown = await api.get("/documents").catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect((err as ApiClientError).status).toBe(401);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it("never attempts refresh for login/refresh/signup paths", async () => {
    const refresh = vi.fn(async () => true);
    setAuthHandler({
      getAccessToken: () => "stale",
      refreshAccessToken: refresh,
      onAuthFailure: () => {},
    });
    stubFetch(() => jsonResponse({ detail: "bad credentials" }, 401, "Unauthorized"));
    await expect(
      request("/security/auth/login", { method: "POST", body: { email: "a", password: "b" } })
    ).rejects.toBeInstanceOf(ApiClientError);
    await expect(
      request("/security/auth/refresh", { method: "POST", body: { refresh_token: "x" } })
    ).rejects.toBeInstanceOf(ApiClientError);
    expect(refresh).not.toHaveBeenCalled();
    expect(calls).toHaveLength(2);
  });

  it("does not loop: a 401 after retry is thrown", async () => {
    setAuthHandler({
      getAccessToken: () => "tok",
      refreshAccessToken: async () => true,
      onAuthFailure: () => {},
    });
    stubFetch(() => jsonResponse({ detail: "still bad" }, 401, "Unauthorized"));
    const err: unknown = await api.get("/documents").catch((e) => e);
    expect((err as ApiClientError).status).toBe(401);
    expect(calls).toHaveLength(2);
  });
});

describe("URL safety", () => {
  it("encodePathSegment escapes slashes, spaces, unicode", () => {
    expect(encodePathSegment("a/b c?d#e")).toBe("a%2Fb%20c%3Fd%23e");
    expect(encodePathSegment("RBI/2024:12")).toBe("RBI%2F2024%3A12");
  });

  it("query builder skips null/undefined", async () => {
    stubFetch(() => jsonResponse({}));
    await api.get("/research", { query: { kind: undefined, page: 2 } });
    expect(calls[0].url).toBe("/api/v1/research?page=2");
  });
});
