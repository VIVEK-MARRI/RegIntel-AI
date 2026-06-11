import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { AgentControlCenterPage } from "@/pages/AgentControlCenterPage";
import { AgentCollaborationPage } from "@/pages/AgentCollaborationPage";
import { AgentHealthPage } from "@/pages/AgentHealthPage";
import { AgentWorkflowsPage } from "@/pages/AgentWorkflowsPage";
import { AuditPage } from "@/pages/AuditPage";
import { AdminPage } from "@/pages/AdminPage";
import { CompliancePage } from "@/pages/CompliancePage";
import { CopilotPage } from "@/pages/CopilotPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { KnowledgeGraphPage } from "@/pages/KnowledgeGraphPage";
import { GovernancePage } from "@/pages/GovernancePage";
import { ResearchPage } from "@/pages/ResearchPage";
import { RiskPage } from "@/pages/RiskPage";
import type { ReactNode } from "react";

function renderPage(node: ReactNode, initialRoute = "/") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialRoute]}>
            <Routes>
              <Route path="*" element={node} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

// Stub fetch — pages issue many calls; we only assert rendering, not network.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    )
  );
});

describe("Pages render", () => {
  it("DashboardPage", async () => {
    renderPage(<DashboardPage />);
    expect(
      await screen.findByText(/Welcome back/i, {}, { timeout: 2000 })
    ).toBeInTheDocument();
  });

  it("SettingsPage", () => {
    renderPage(<SettingsPage />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("NotFoundPage", () => {
    renderPage(<NotFoundPage />);
    expect(screen.getByText(/Page not found/i)).toBeInTheDocument();
  });

  it("AgentControlCenterPage renders header", () => {
    renderPage(<AgentControlCenterPage />);
    expect(screen.getByText(/Agent Control Center/i)).toBeInTheDocument();
  });

  it("AgentCollaborationPage", () => {
    renderPage(<AgentCollaborationPage />);
    expect(screen.getByText("Collaborations")).toBeInTheDocument();
  });

  it("AgentHealthPage", () => {
    renderPage(<AgentHealthPage />);
    expect(screen.getByText(/Agent Health Dashboard/i)).toBeInTheDocument();
  });

  it("AgentWorkflowsPage", () => {
    renderPage(<AgentWorkflowsPage />);
    expect(screen.getByText("Workflows")).toBeInTheDocument();
  });

  it("AuditPage", () => {
    renderPage(<AuditPage />);
    expect(screen.getByText("Audit")).toBeInTheDocument();
  });

  it("AdminPage", () => {
    renderPage(<AdminPage />);
    expect(screen.getByText(/Admin Console/i)).toBeInTheDocument();
  });

  it("CompliancePage", () => {
    renderPage(<CompliancePage />);
    expect(screen.getByText("Compliance")).toBeInTheDocument();
  });

  it("CopilotPage", () => {
    renderPage(<CopilotPage />);
    expect(screen.getByText("Copilot")).toBeInTheDocument();
  });

  it("KnowledgeGraphPage", () => {
    renderPage(<KnowledgeGraphPage />);
    expect(screen.getByText(/Node types/i)).toBeInTheDocument();
  });

  it("GovernancePage", () => {
    renderPage(<GovernancePage />);
    expect(screen.getByText("Governance")).toBeInTheDocument();
  });

  it("ResearchPage", () => {
    renderPage(<ResearchPage />);
    expect(screen.getByText("Research")).toBeInTheDocument();
  });

  it("RiskPage", () => {
    renderPage(<RiskPage />);
    expect(screen.getByText("Risk")).toBeInTheDocument();
  });
});
