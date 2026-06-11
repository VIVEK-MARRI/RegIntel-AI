import { lazy, Suspense, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Sidebar, Topbar } from "@/components/layout/AppShell";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RequireRole } from "@/components/auth/RequireRole";

const LoginPage = lazy(() =>
  import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage }))
);
const SignupPage = lazy(() =>
  import("@/pages/SignupPage").then((m) => ({ default: m.SignupPage }))
);
const DashboardPage = lazy(() =>
  import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage }))
);
const CopilotPage = lazy(() =>
  import("@/pages/CopilotPage").then((m) => ({ default: m.CopilotPage }))
);
const ResearchPage = lazy(() =>
  import("@/pages/ResearchPage").then((m) => ({ default: m.ResearchPage }))
);
const CompliancePage = lazy(() =>
  import("@/pages/CompliancePage").then((m) => ({ default: m.CompliancePage }))
);
const RiskPage = lazy(() =>
  import("@/pages/RiskPage").then((m) => ({ default: m.RiskPage }))
);
const KnowledgeGraphPage = lazy(() =>
  import("@/pages/KnowledgeGraphPage").then((m) => ({
    default: m.KnowledgeGraphPage,
  }))
);
const AgentControlCenterPage = lazy(() =>
  import("@/pages/AgentControlCenterPage").then((m) => ({
    default: m.AgentControlCenterPage,
  }))
);
const AgentCollaborationPage = lazy(() =>
  import("@/pages/AgentCollaborationPage").then((m) => ({
    default: m.AgentCollaborationPage,
  }))
);
const AgentHealthPage = lazy(() =>
  import("@/pages/AgentHealthPage").then((m) => ({ default: m.AgentHealthPage }))
);
const AgentWorkflowsPage = lazy(() =>
  import("@/pages/AgentWorkflowsPage").then((m) => ({
    default: m.AgentWorkflowsPage,
  }))
);
const GovernancePage = lazy(() =>
  import("@/pages/GovernancePage").then((m) => ({ default: m.GovernancePage }))
);
const AuditPage = lazy(() =>
  import("@/pages/AuditPage").then((m) => ({ default: m.AuditPage }))
);
const AnalyticsPage = lazy(() =>
  import("@/pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage }))
);
const DocumentsPage = lazy(() =>
  import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage }))
);
const AdminPage = lazy(() =>
  import("@/pages/AdminPage").then((m) => ({ default: m.AdminPage }))
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage }))
);
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage }))
);

const ROLE_PROTECTED_ROUTES: Record<string, string[]> = {
  "/admin": ["admin"],
  "/governance": ["admin", "auditor"],
  "/audit": ["admin", "auditor"],
  "/analytics": ["admin", "analyst", "operator"],
  "/agents": ["admin", "operator", "analyst"],
  "/agents/collaboration": ["admin", "operator"],
  "/agents/health": ["admin", "operator"],
  "/agents/workflows": ["admin", "operator"],
};

function routeRoles(path: string): string[] | undefined {
  if (ROLE_PROTECTED_ROUTES[path]) return ROLE_PROTECTED_ROUTES[path];
  if (path.startsWith("/agents/")) return ROLE_PROTECTED_ROUTES["/agents"];
  return undefined;
}

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar collapsed={collapsed} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onToggleSidebar={() => setCollapsed((v) => !v)} />
        <main className="flex-1 overflow-y-auto bg-surface-light-2 p-4 sm:p-6 dark:bg-surface-dark">
          {children}
        </main>
      </div>
      <ToastViewport />
    </div>
  );
}

function ProtectedRouteWithRole({
  path,
  element,
}: {
  path: string;
  element: React.ReactNode;
}) {
  const roles = routeRoles(path);
  const content = roles ? (
    <RequireRole roles={roles}>{element}</RequireRole>
  ) : (
    element
  );
  return <ProtectedRoute>{content}</ProtectedRoute>;
}

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
    </div>
  );
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route
          path="/*"
          element={
            <Suspense fallback={<PageFallback />}>
              <ProtectedLayout>
                <Routes>
                <Route
                  path="/"
                  element={
                    <ProtectedRouteWithRole path="/" element={<DashboardPage />} />
                  }
                />
                <Route
                  path="/copilot"
                  element={
                    <ProtectedRouteWithRole
                      path="/copilot"
                      element={<CopilotPage />}
                    />
                  }
                />
                <Route
                  path="/copilot/:conversationId"
                  element={
                    <ProtectedRouteWithRole
                      path="/copilot"
                      element={<CopilotPage />}
                    />
                  }
                />
                <Route
                  path="/research"
                  element={
                    <ProtectedRouteWithRole
                      path="/research"
                      element={<ResearchPage />}
                    />
                  }
                />
                <Route
                  path="/research/:reportId"
                  element={
                    <ProtectedRouteWithRole
                      path="/research"
                      element={<ResearchPage />}
                    />
                  }
                />
                <Route
                  path="/compliance"
                  element={
                    <ProtectedRouteWithRole
                      path="/compliance"
                      element={<CompliancePage />}
                    />
                  }
                />
                <Route
                  path="/compliance/:assessmentId"
                  element={
                    <ProtectedRouteWithRole
                      path="/compliance"
                      element={<CompliancePage />}
                    />
                  }
                />
                <Route
                  path="/risk"
                  element={
                    <ProtectedRouteWithRole path="/risk" element={<RiskPage />} />
                  }
                />
                <Route
                  path="/knowledge-graph"
                  element={
                    <ProtectedRouteWithRole
                      path="/knowledge-graph"
                      element={<KnowledgeGraphPage />}
                    />
                  }
                />
                <Route
                  path="/agents"
                  element={
                    <ProtectedRouteWithRole
                      path="/agents"
                      element={<AgentControlCenterPage />}
                    />
                  }
                />
                <Route
                  path="/agents/collaboration"
                  element={
                    <ProtectedRouteWithRole
                      path="/agents/collaboration"
                      element={<AgentCollaborationPage />}
                    />
                  }
                />
                <Route
                  path="/agents/health"
                  element={
                    <ProtectedRouteWithRole
                      path="/agents/health"
                      element={<AgentHealthPage />}
                    />
                  }
                />
                <Route
                  path="/agents/workflows"
                  element={
                    <ProtectedRouteWithRole
                      path="/agents/workflows"
                      element={<AgentWorkflowsPage />}
                    />
                  }
                />
                <Route
                  path="/governance"
                  element={
                    <ProtectedRouteWithRole
                      path="/governance"
                      element={<GovernancePage />}
                    />
                  }
                />
                <Route
                  path="/audit"
                  element={
                    <ProtectedRouteWithRole
                      path="/audit"
                      element={<AuditPage />}
                    />
                  }
                />
                <Route
                  path="/analytics"
                  element={
                    <ProtectedRouteWithRole
                      path="/analytics"
                      element={<AnalyticsPage />}
                    />
                  }
                />
                <Route
                  path="/documents"
                  element={
                    <ProtectedRouteWithRole
                      path="/documents"
                      element={<DocumentsPage />}
                    />
                  }
                />
                <Route
                  path="/admin"
                  element={
                    <ProtectedRouteWithRole
                      path="/admin"
                      element={<AdminPage />}
                    />
                  }
                />
                <Route
                  path="/settings"
                  element={
                    <ProtectedRouteWithRole
                      path="/settings"
                      element={<SettingsPage />}
                    />
                  }
                />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
              </ProtectedLayout>
            </Suspense>
          }
        />
      </Routes>
    </Suspense>
  );
}
