/**
 * Stage 16 settings tests: authoritative identity, browser-local theme
 * preference (light/dark/system), honest session facts with working sign
 * out, read-only access-model reference, and explicit unsupported-capability
 * messaging with no fake controls. MSW uses backend-shaped payloads
 * (/security/auth/me + /security/roles).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsPage } from "@/pages/SettingsPage";
import { LoginPage } from "@/pages/LoginPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { AuthProvider } from "@/providers/AuthProvider";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const server = setupServer(
  http.get("/api/v1/security/auth/me", async () => {
    return HttpResponse.json({ subject_id: "u1", roles: ["analyst"], scopes: ["read"], permissions: ["documents:read"] });
  }),
  http.get("/api/v1/security/roles", async () => {
    return HttpResponse.json({
      roles: { analyst: ["documents:read", "research:run"], viewer: [] },
      permissions: ["documents:read", "research:run"],
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  setAccessToken(null);
  setAuthHandler(null);
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <MemoryRouter initialEntries={["/settings"]}>
              <Routes>
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/login" element={<LoginPage />} />
              </Routes>
            </MemoryRouter>
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

describe("page structure", () => {
  it("h1 and exactly the supported sections render", async () => {
    renderSettings();
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    expect(await screen.findByText("Account")).toBeTruthy();
    for (const name of ["Appearance", "Session", "Access model", "Not available", "About"]) {
      expect(screen.getByText(name)).toBeTruthy();
    }
  });

  it("no fabricated controls: density, API keys, providers, flags are gone", async () => {
    renderSettings();
    await screen.findByText("Account");
    for (const pat of [/density/i, /api key/i, /llm provider/i, /embedding/i, /reranker/i, /feature flag/i, /storage/i]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});

describe("identity", () => {
  it("subject, roles, scopes, permissions render from /me", async () => {
    renderSettings();
    expect(await screen.findByText("u1")).toBeTruthy();
    // Identity badges and the access-model reference can both be on screen.
    expect(screen.getAllByText("analyst").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("documents:read").length).toBeGreaterThanOrEqual(1);
  });

  it("identity failure is retryable", async () => {
    server.use(
      http.get("/api/v1/security/auth/me", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderSettings();
    expect(await screen.findByText("Account unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("appearance (local only)", () => {
  it("select reflects the stored preference and labels browser storage", async () => {
    renderSettings();
    await screen.findByText("Account");
    expect(screen.getByText("Local only")).toBeTruthy();
    expect(screen.getByText(/stored on this browser/i)).toBeTruthy();
    expect((screen.getByLabelText(/^theme$/i) as HTMLSelectElement).value).toBe("system");
  });

  it("choosing dark applies immediately and persists locally", async () => {
    renderSettings();
    await screen.findByText("Account");
    fireEvent.change(screen.getByLabelText(/^theme$/i), { target: { value: "dark" } });
    await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
    expect(window.localStorage.getItem("regintel:theme")).toBe("dark");
    expect(screen.getByText(/currently applied: dark/i)).toBeTruthy();
  });

  it("system preference follows the device and survives remount", async () => {
    const first = renderSettings();
    await screen.findByText("Account");
    fireEvent.change(screen.getByLabelText(/^theme$/i), { target: { value: "system" } });
    expect(window.localStorage.getItem("regintel:theme")).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    first.unmount();
    renderSettings();
    await screen.findByText("Account");
    expect((screen.getByLabelText(/^theme$/i) as HTMLSelectElement).value).toBe("system");
  });
});

describe("session", () => {
  it("states local token facts without inventing server sessions", async () => {
    renderSettings();
    await screen.findByText("Account");
    expect(screen.getByText(/access token lives only in this tab/i)).toBeTruthy();
    expect(screen.getByText(/no session list/i)).toBeTruthy();
    expect(screen.queryByText(/active sessions/i)).toBeNull();
    expect(screen.queryByText(/devices/i)).toBeNull();
  });

  it("sign out clears local auth and lands on login", async () => {
    renderSettings();
    await screen.findByText("Account");
    await userEvent.click(screen.getByRole("button", { name: "Sign out of this browser" }));
    expect(await screen.findByText(/sign in to continue/i)).toBeTruthy();
  });
});

describe("access model", () => {
  it("built-in roles render with their grants, read-only", async () => {
    renderSettings();
    await screen.findByText("Account");
    // "analyst" appears twice by design: identity badge + access-model heading.
    expect(screen.getAllByText("analyst")).toHaveLength(2);
    expect(screen.getByText("research:run")).toBeTruthy();
    expect(screen.getByText("viewer")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /save|update|edit/i })).toBeNull();
  });

  it("access model failure is retryable", async () => {
    server.use(
      http.get("/api/v1/security/roles", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderSettings();
    expect(await screen.findByText("Access model unavailable")).toBeTruthy();
  });
});

describe("unsupported capabilities", () => {
  it("names missing backends as limitations, not empty datasets", async () => {
    renderSettings();
    await screen.findByText("Account");
    expect(screen.getByText(/password changes/i)).toBeTruthy();
    expect(screen.getByText(/notification preferences/i)).toBeTruthy();
    expect(screen.getByText(/missing backend capability/i)).toBeTruthy();
  });

  it("links to Administration instead of duplicating it", async () => {
    renderSettings();
    await screen.findByText("Account");
    const links = screen.getAllByRole("link", { name: "Administration" });
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(links[0].getAttribute("href")).toBe("/admin");
    expect(screen.queryByText(/platform setting/i)).toBeNull();
  });
});

describe("ux/a11y", () => {
  it("labelled controls and alert errors", async () => {
    renderSettings();
    await screen.findByText("Account");
    expect(screen.getByLabelText(/^theme$/i)).toBeTruthy();
    server.use(
      http.get("/api/v1/security/auth/me", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    const second = renderSettings();
    expect(await second.findByText("Account unavailable")).toBeTruthy();
    expect(second.getByRole("alert")).toBeTruthy();
    second.unmount();
  });
});
