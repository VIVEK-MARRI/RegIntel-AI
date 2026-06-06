import { Route, Routes } from "react-router-dom";
import { useState } from "react";
import { Sidebar, Topbar } from "@/components/layout/AppShell";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { DashboardPage } from "@/pages/DashboardPage";
import { CopilotPage } from "@/pages/CopilotPage";
import { ResearchPage } from "@/pages/ResearchPage";
import { CompliancePage } from "@/pages/CompliancePage";
import { RiskPage } from "@/pages/RiskPage";
import { KnowledgeGraphPage } from "@/pages/KnowledgeGraphPage";
import { AgentControlCenterPage } from "@/pages/AgentControlCenterPage";
import { AgentCollaborationPage } from "@/pages/AgentCollaborationPage";
import { AgentHealthPage } from "@/pages/AgentHealthPage";
import { AgentWorkflowsPage } from "@/pages/AgentWorkflowsPage";
import { GovernancePage } from "@/pages/GovernancePage";
import { AuditPage } from "@/pages/AuditPage";
import { AdminPage } from "@/pages/AdminPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar collapsed={collapsed} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onToggleSidebar={() => setCollapsed((v) => !v)} />
        <main className="flex-1 overflow-y-auto bg-surface-light-2 p-4 sm:p-6 dark:bg-surface-dark">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/copilot" element={<CopilotPage />} />
            <Route path="/copilot/:conversationId" element={<CopilotPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/research/:reportId" element={<ResearchPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/compliance/:assessmentId" element={<CompliancePage />} />
            <Route path="/risk" element={<RiskPage />} />
            <Route path="/knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route path="/agents" element={<AgentControlCenterPage />} />
            <Route path="/agents/collaboration" element={<AgentCollaborationPage />} />
            <Route path="/agents/health" element={<AgentHealthPage />} />
            <Route path="/agents/workflows" element={<AgentWorkflowsPage />} />
            <Route path="/governance" element={<GovernancePage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
      <ToastViewport />
    </div>
  );
}
