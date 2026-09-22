/**
 * Stage 03 auth tests: observable session behavior (no hollow asserts).
 * MSW replies with backend-shaped payloads; every test proves a state
 * transition, redirect, refresh, cleanup, or role outcome.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpResponse, delay, http } from "msw";
import { setupServer } from "msw/node";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AuthProvider,
  authErrorMessage,
  getSafeRedirect,
  normalizeRoles,
  resolveDemoAccess,
  useAuth,
  type AuthState,
} from "@/providers/AuthProvider";
import { setAccessToken } from "@/lib/auth-token";
import { api, setAuthHandler } from "@/lib/api";
import { ApiClientError } from "@/lib/errors";

let refreshCalls = 0;

const server = setupServer(
  http.post("/api/v1/security/auth/login", async () => {
    return HttpResponse.json({
      access_token: "acc-1",
      refresh_token: "ref-1",
      token_type: "Bearer",
      expires_in: 40,
      access_expires_at: "2026-01-01T00:00:40+00:00",
      refresh_expires_at: "2026-01-02T00:00:00+00:00",
      user: {
        user_id: "u-1",
        username: "analyst@x.io",
        email: "analyst@x.io",
        full_name: "Analyst",
        roles: ["Analyst"],
        rbac_roles: ["analyst", "ADMIN", "bogus-role"],
      },
    });
  }),
  http.post("/api/v1/security/auth/refresh", async () => {
    refreshCalls += 1;
    return HttpResponse.json({
      access_token: `acc-r${refreshCalls}`,
      refresh_token: `ref-r${refreshCalls}`,
      token_type: "Bearer",
      expires_in: 40,
      access_expires_at: "2026-01-01T00:00:40+00:00",
      refresh_expires_at: "2026-01-02T00:00:00+00:00",
    });
  }),
  http.get("/api/v1/security/auth/me", async () => {
    return HttpResponse.json({
      subject_id: "u-1",
      roles: ["analyst"],
      scopes: [],
      permissions: [],
    });
  }),
  http.get("/api/v1/documents", async () => {
    return HttpResponse.json([]);
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  refreshCalls = 0;
});
afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());

let latest: AuthState | null = null;

function Probe() {
  const auth = useAuth();
  latest = auth;
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="user">{auth.user ? auth.user.email : "none"}</span>
      <span data-testid="demo">{String(auth.demoMode)}</span>
      <span data-testid="auth-error">{auth.authError ?? ""}</span>
      <button type="button" onClick={() => void auth.login("analyst@x.io", "pw123456")}>
        do-login
      </button>
      <button type="button" onClick={() => auth.logout()}>
        do-logout
      </button>
      <button type="button" onClick={() => void auth.refreshSession()}>
        do-refresh
      </button>
    </div>
  );
}

function renderProbe() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { ...utils, qc };
}

/**
 * Flush bootstrap under fake timers. React 18 schedules work through
 * MessageChannel (real macrotasks), so one advance rarely suffices —
 * poll until the status reaches the target.
 */
async function awaitStatus(text: string) {
  for (let i = 0; i < 30; i++) {
    if (screen.getByTestId("status").textContent === text) return;
    await vi.advanceTimersByTimeAsync(200);
  }
  throw new Error(`status did not become ${text}`);
}

describe("bootstrap", () => {
  it("A. no persisted session -> unauthenticated without network", async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(refreshCalls).toBe(0);
    expect(screen.getByTestId("user").textContent).toBe("none");
  });

  it("B. stored refresh -> refresh + /me -> authenticated with server roles", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    localStorage.setItem(
      "regintel_user",
      JSON.stringify({ user_id: "u-1", email: "stale@x.io", username: "s", full_name: "", roles: ["admin"], rbac_roles: ["admin"] })
    );
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    // /me roles win over the tampered cache: no admin anywhere.
    expect(latest!.user!.roles).toEqual(["analyst"]);
    expect(latest!.user!.rbac_roles).toEqual(["analyst"]);
    expect(latest!.hasRole("analyst")).toBe(true);
    expect(latest!.hasRole("admin")).toBe(false);
  });

  it("C. failed bootstrap refresh -> unauthenticated + storage cleared", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-bad");
    localStorage.setItem("regintel_user", JSON.stringify({ user_id: "u-1", email: "a@b" }));
    server.use(
      http.post("/api/v1/security/auth/refresh", async () => {
        return HttpResponse.json({ detail: "revoked" }, { status: 401 });
      })
    );
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(localStorage.getItem("regintel_refresh_token")).toBeNull();
    expect(localStorage.getItem("regintel_user")).toBeNull();
  });

  it("O. malformed persisted user cannot crash bootstrap", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    localStorage.setItem("regintel_user", "{broken-json");
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(latest!.user!.email).toBe("u-1");
  });
});

describe("login / logout", () => {
  it("D. successful login establishes session + schedules refresh", async () => {
    vi.useFakeTimers();
    try {
      renderProbe();
      await awaitStatus("unauthenticated");
      screen.getByText("do-login").click();
      await awaitStatus("authenticated");
      expect(screen.getByTestId("user").textContent).toBe("analyst@x.io");
      expect(localStorage.getItem("regintel_refresh_token")).toBe("ref-1");
      // proactive timer: expires_in=40 -> fires at ~10s -> second refresh.
      await vi.advanceTimersByTimeAsync(11_000);
      expect(refreshCalls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("E. failed login (401) stays unauthenticated with a safe message", async () => {
    server.use(
      http.post("/api/v1/security/auth/login", async () => {
        return HttpResponse.json({ detail: "invalid email or password" }, { status: 401 });
      })
    );
    let thrown = "";
    function FailProbe() {
      const auth = useAuth();
      latest = auth;
      return (
        <button
          type="button"
          onClick={() => auth.login("a@b.c", "wrong").catch((e: unknown) => {
            thrown = e instanceof Error ? e.message : "";
          })}
        >
          do-login
        </button>
      );
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <AuthProvider>
            <FailProbe />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(latest!.status).toBe("unauthenticated"));
    screen.getByText("do-login").click();
    // The provider propagates the backend detail; pages map it via
    // authErrorMessage (covered in auth-guards + unit tests below).
    await waitFor(() => expect(thrown).toBe("invalid email or password"));
    expect(latest!.status).toBe("unauthenticated");
    expect(localStorage.getItem("regintel_refresh_token")).toBeNull();
  });

  it("F. logout clears tokens, user, timers, and query cache", async () => {
    const { qc } = renderProbe();
    screen.getByText("do-login").click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    qc.setQueryData(["documents"], [{ id: "d1" }]);
    screen.getByText("do-logout").click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(localStorage.getItem("regintel_refresh_token")).toBeNull();
    expect(localStorage.getItem("regintel_user")).toBeNull();
    expect(qc.getQueryData(["documents"])).toBeUndefined();
    expect(screen.getByTestId("user").textContent).toBe("none");
  });

  it("G+H. refresh timer reschedules; unmount cleans it up", async () => {
    vi.useFakeTimers();
    try {
      localStorage.setItem("regintel_refresh_token", "ref-old");
      const { unmount } = renderProbe();
      await awaitStatus("authenticated");
      expect(refreshCalls).toBe(1);
      await vi.advanceTimersByTimeAsync(11_000);
      expect(refreshCalls).toBe(2);
      unmount();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(refreshCalls).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("401 recovery integration", () => {
  function flakyResource() {
    let hits = 0;
    server.use(
      http.get("/api/v1/flaky", async ({ request }) => {
        hits += 1;
        // Only the ROTATED token works: bootstrap leaves acc-r1, so the
        // first attempt 401s and must trigger exactly one rotation to acc-r2.
        const auth = request.headers.get("authorization");
        if (auth === "Bearer acc-r2") {
          return HttpResponse.json({ ok: true });
        }
        return HttpResponse.json({ detail: "expired" }, { status: 401 });
      })
    );
    return () => hits;
  }

  it("I. 401 -> one refresh -> retry succeeds", async () => {
    const hits = flakyResource();
    localStorage.setItem("regintel_refresh_token", "ref-old");
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    const before = refreshCalls;
    const res = await api.get<{ ok: boolean }>("/flaky");
    expect(res).toEqual({ ok: true });
    expect(refreshCalls).toBe(before + 1);
    expect(hits()).toBe(2);
  });

  it("J. concurrent 401s share ONE refresh", async () => {
    const hits = flakyResource();
    localStorage.setItem("regintel_refresh_token", "ref-old");
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    const before = refreshCalls;
    const results = await Promise.all([
      api.get("/flaky"),
      api.get("/flaky"),
      api.get("/flaky"),
    ]);
    expect(results).toHaveLength(3);
    expect(refreshCalls).toBe(before + 1);
    expect(hits()).toBe(6);
  });

  it("K. refresh failure terminates the session cleanly", async () => {
    server.use(
      http.post("/api/v1/security/auth/refresh", async () => {
        return HttpResponse.json({ detail: "revoked" }, { status: 401 });
      })
    );
    localStorage.setItem("regintel_refresh_token", "ref-old");
    renderProbe();
    // bootstrap itself fails -> unauthenticated, storage wiped.
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(localStorage.getItem("regintel_refresh_token")).toBeNull();
  });

  it("L. retry 401 does not loop and keeps the fresh session", async () => {
    server.use(
      http.get("/api/v1/always-bad", async () => {
        return HttpResponse.json({ detail: "denied" }, { status: 401 });
      })
    );
    localStorage.setItem("regintel_refresh_token", "ref-old");
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    const before = refreshCalls;
    const err: unknown = await api.get("/always-bad").catch((e) => e);
    expect((err as ApiClientError).status).toBe(401);
    // one retry only: bootstrap(1) + rotation(1) + original + retry = bounded.
    expect(refreshCalls).toBe(before + 1);
    expect(screen.getByTestId("status").textContent).toBe("authenticated");
  });

  it("Y. logout during a pending request clears session + cache", async () => {
    server.use(
      http.get("/api/v1/slow", async () => {
        await delay(300);
        return HttpResponse.json([]);
      })
    );
    const { qc } = renderProbe();
    screen.getByText("do-login").click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    qc.setQueryData(["documents"], [{ id: "d1" }]);
    const pending = api.get("/slow");
    screen.getByText("do-logout").click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(qc.getQueryData(["documents"])).toBeUndefined();
    await pending.catch(() => undefined);
  });

  it("Z. login clears the previous identity's cache", async () => {
    const { qc } = renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    qc.setQueryData(["documents"], [{ id: "stale" }]);
    screen.getByText("do-login").click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(qc.getQueryData(["documents"])).toBeUndefined();
  });
});

describe("revalidation + roles", () => {
  it("M. /me roles override stale persisted roles on bootstrap", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    localStorage.setItem(
      "regintel_user",
      JSON.stringify({ user_id: "u-1", email: "x@y", username: "x", full_name: "", roles: ["service"], rbac_roles: ["service"] })
    );
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(latest!.user!.roles).toEqual(["analyst"]);
    expect(latest!.hasRole("service")).toBe(false);
  });

  it("N. normalizeRoles drops unknown/malformed entries, dedupes, lowercases", () => {
    expect(normalizeRoles(["ADMIN", "admin", "bogus", 42, null, "Viewer"])).toEqual([
      "admin",
      "viewer",
    ]);
    expect(normalizeRoles("operator")).toEqual(["operator"]);
    expect(normalizeRoles(undefined)).toEqual([]);
  });

  it("getSafeRedirect only allows same-origin app paths", () => {
    expect(getSafeRedirect("/compliance?a=1#x")).toBe("/compliance?a=1#x");
    expect(getSafeRedirect("//evil.com")).toBe("/");
    expect(getSafeRedirect("https://evil.com")).toBe("/");
    expect(getSafeRedirect("javascript:alert(1)")).toBe("/");
    expect(getSafeRedirect(undefined)).toBe("/");
    expect(getSafeRedirect(42)).toBe("/");
  });
});

describe("demo mode", () => {
  it("P. explicit flag in dev installs an obvious demo session", async () => {
    vi.stubEnv("VITE_AUTH_ENABLED", "false");
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByTestId("demo").textContent).toBe("true");
    expect(latest!.hasRole("admin")).toBe(true);
  });

  it("Q. production builds refuse demo (fail closed)", () => {
    expect(resolveDemoAccess(true, true)).toBe("deny");
    expect(resolveDemoAccess(true, false)).toBe("allow");
    expect(resolveDemoAccess(false, false)).toBe("deny");
    expect(resolveDemoAccess(false, true)).toBe("deny");
  });
});

describe("auth error messages", () => {
  it("maps statuses to safe specific messages", () => {
    expect(
      authErrorMessage(new ApiClientError(0, "x", undefined, "network"), "login")
    ).toContain("Cannot reach");
    expect(
      authErrorMessage(new ApiClientError(401, "invalid email or password"), "login")
    ).toBe("Invalid email or password.");
    expect(
      authErrorMessage(new ApiClientError(401, "expired"), "session")
    ).toBe("Your session has expired. Please sign in again.");
    expect(
      authErrorMessage(new ApiClientError(429, "slow"), "login")
    ).toContain("Too many");
    expect(authErrorMessage(new Error("boom"), "login")).toBe("boom");
  });
});
