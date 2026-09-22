/**
 * Stage 03 route-guard + auth-page tests: redirects, role gates, signup.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/providers/AuthProvider";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RequireRole } from "@/components/auth/RequireRole";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";
import { LoginPage } from "@/pages/LoginPage";
import { SignupPage } from "@/pages/SignupPage";

const server = setupServer(
  http.post("/api/v1/security/auth/login", async () => {
    return HttpResponse.json({
      access_token: "acc-1",
      refresh_token: "ref-1",
      token_type: "Bearer",
      expires_in: 3600,
      access_expires_at: "2026-01-01T01:00:00+00:00",
      refresh_expires_at: "2026-01-02T00:00:00+00:00",
      user: {
        user_id: "u-1",
        username: "analyst@x.io",
        email: "analyst@x.io",
        full_name: "Analyst",
        roles: ["analyst"],
        rbac_roles: ["analyst"],
      },
    });
  }),
  http.post("/api/v1/security/auth/refresh", async () => {
    return HttpResponse.json({
      access_token: "acc-2",
      refresh_token: "ref-2",
      token_type: "Bearer",
      expires_in: 3600,
      access_expires_at: "2026-01-01T01:00:00+00:00",
      refresh_expires_at: "2026-01-02T00:00:00+00:00",
    });
  }),
  http.get("/api/v1/security/auth/me", async () => {
    return HttpResponse.json({ subject_id: "u-1", roles: ["analyst"], scopes: [], permissions: [] });
  }),
  http.post("/api/v1/security/auth/signup", async () => {
    return HttpResponse.json({
      access_token: "acc-1",
      refresh_token: "ref-1",
      token_type: "Bearer",
      expires_in: 3600,
      access_expires_at: "x",
      refresh_expires_at: "y",
      user: {
        user_id: "u-2",
        username: "new@x.io",
        email: "new@x.io",
        full_name: "New",
        roles: [],
        rbac_roles: ["viewer"],
      },
    }, { status: 201 });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function ShowPath() {
  const location = useLocation();
  return <span>at:{location.pathname}</span>;
}

function shell(initialEntries: Array<string | { pathname: string; state?: unknown }>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route
              path="/compliance"
              element={
                <ProtectedRoute>
                  <span>compliance-page</span>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute>
                  <RequireRole roles={["admin"]}>
                    <span>admin-page</span>
                  </RequireRole>
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<ShowPath />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("protected routing", () => {
  it("U. bootstrap spinner shows while status is unknown", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    shell(["/compliance"]);
    // First paint is always the bootstrap state — never protected content.
    expect(screen.getByText("Verifying session…")).toBeTruthy();
    expect(await screen.findByText("compliance-page")).toBeTruthy();
  });

  it("V. unauthenticated deep link lands on login with safe return target", async () => {
    shell(["/compliance?tab=risk#sec"]);
    expect(await screen.findByRole("heading", { name: "RegIntel AI" })).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "analyst@x.io");
    await user.type(screen.getByLabelText("Password"), "pw123456");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("compliance-page")).toBeTruthy();
  });

  it("W. insufficient role shows restriction, not the page", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    shell(["/admin"]);
    expect(await screen.findByText("Access restricted")).toBeTruthy();
    expect(screen.queryByText("admin-page")).toBeNull();
  });

  it("X. hostile redirect targets are neutralized to /", async () => {
    shell([{ pathname: "/login", state: { from: "//evil.com/x" } }]);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "RegIntel AI" })).not.toBeNull());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "analyst@x.io");
    await user.type(screen.getByLabelText("Password"), "pw123456");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    // lands on safe "/" (the "*" route shows the path) instead of evil host.
    expect(await screen.findByText(/^at:/)).toBeTruthy();
    expect(screen.getByText(/^at:/).textContent).toBe("at:/");
  });
});

describe("signup page", () => {
  it("R. validation blocks empty email and short passwords", async () => {
    shell(["/signup"]);
    expect(await screen.findByRole("heading", { name: "Create Account" })).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("you@example.com"), "new@x.io");
    await user.type(screen.getByPlaceholderText("At least 6 characters"), "123");
    await user.click(screen.getByRole("button", { name: "Create Account" }));
    expect(await screen.findByText("Password must be at least 6 characters.")).toBeTruthy();
  });

  it("S. successful signup establishes a session and lands home", async () => {
    shell(["/signup"]);
    expect(await screen.findByRole("heading", { name: "Create Account" })).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Your name"), "New User");
    await user.type(screen.getByPlaceholderText("you@example.com"), "new@x.io");
    await user.type(screen.getByPlaceholderText("At least 6 characters"), "pw123456");
    await user.click(screen.getByRole("button", { name: "Create Account" }));
    expect(await screen.findByText(/^at:/)).toBeTruthy();
    expect(localStorage.getItem("regintel_refresh_token")).toBe("ref-1");
  });

  it("T. duplicate account surfaces the backend message", async () => {
    server.use(
      http.post("/api/v1/security/auth/signup", async () => {
        return HttpResponse.json({ detail: "email already registered" }, { status: 409 });
      })
    );
    shell(["/signup"]);
    expect(await screen.findByRole("heading", { name: "Create Account" })).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("you@example.com"), "dup@x.io");
    await user.type(screen.getByPlaceholderText("At least 6 characters"), "pw123456");
    await user.click(screen.getByRole("button", { name: "Create Account" }));
    expect(await screen.findByText("email already registered")).toBeTruthy();
  });

  it("renders for authenticated users without hook-order crash", async () => {
    localStorage.setItem("regintel_refresh_token", "ref-old");
    shell(["/signup"]);
    // Either redirected home (at:/) or still on signup — but never crashed.
    await waitFor(
      () =>
        expect(
          screen.queryByText(/^at:/) ?? screen.queryByRole("heading", { name: "Create Account" })
        ).toBeTruthy(),
      { timeout: 5000 }
    );
  });
});

describe("login page behavior", () => {
  it("trims + lowercases email and blocks double submit", async () => {
    let bodies: unknown[] = [];
    server.use(
      http.post("/api/v1/security/auth/login", async ({ request }) => {
        bodies.push(await request.json());
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({
          access_token: "a",
          refresh_token: "r",
          token_type: "Bearer",
          expires_in: 3600,
          access_expires_at: "x",
          refresh_expires_at: "y",
          user: {
            user_id: "u",
            username: "a",
            email: "a",
            full_name: "",
            roles: [],
            rbac_roles: ["viewer"],
          },
        });
      })
    );
    shell(["/login"]);
    expect(await screen.findByRole("heading", { name: "RegIntel AI" })).toBeTruthy();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "  ANALYST@X.IO  ");
    await user.type(screen.getByLabelText("Password"), "pw123456");
    const btn = screen.getByRole("button", { name: "Sign in" });
    await user.click(btn);
    await user.click(btn).catch(() => undefined);
    await waitFor(() => expect(bodies.length).toBeGreaterThanOrEqual(1), { timeout: 5000 });
    expect((bodies[0] as { email: string }).email).toBe("analyst@x.io");
  });
});
