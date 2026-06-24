import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Sidebar, Topbar } from "@/components/layout/AppShell";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RequireRole } from "@/components/auth/RequireRole";

const LoginPage = lazy(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const SignupPage = lazy(() => import("@/pages/SignupPage").then((m) => ({ default: m.SignupPage })));
const DashboardPage = lazy(() => import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const CopilotPage = lazy(() => import("@/pages/CopilotPage").then((m) => ({ default: m.CopilotPage })));
const ResearchPage = lazy(() => import("@/pages/ResearchPage").then((m) => ({ default: m.ResearchPage })));
const DocumentsPage = lazy(() => import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage })));
const KnowledgeGraphPage = lazy(() => import("@/pages/KnowledgeGraphPage").then((m) => ({ default: m.KnowledgeGraphPage })));
const CompliancePage = lazy(() => import("@/pages/CompliancePage").then((m) => ({ default: m.CompliancePage })));
const AuditPage = lazy(() => import("@/pages/AuditPage").then((m) => ({ default: m.AuditPage })));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const AgentsPage = lazy(() => import("@/pages/AgentsPage").then((m) => ({ default: m.AgentsPage })));
const AdminPage = lazy(() => import("@/pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar collapsed={false} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onToggleSidebar={() => {}} />
        <main className="flex-1 overflow-y-auto bg-surface-light-2 p-4 sm:p-6 dark:bg-surface-dark">
          {children}
        </main>
      </div>
      <ToastViewport />
    </div>
  );
}

function Protect({ path, children }: { path: string; children: React.ReactNode }) {
  const roleProtected: Record<string, string[]> = {
    "/agents": ["admin", "operator", "analyst"],
    "/admin": ["admin"],
  };
  const roles = Object.entries(roleProtected).find(([prefix]) =>
    path === prefix || path.startsWith(prefix + "/")
  )?.[1];
  const content = roles ? <RequireRole roles={roles}>{children}</RequireRole> : children;
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
                  <Route path="/" element={<Protect path="/"><DashboardPage /></Protect>} />
                  <Route path="/copilot" element={<Protect path="/copilot"><CopilotPage /></Protect>} />
                  <Route path="/copilot/:conversationId" element={<Protect path="/copilot"><CopilotPage /></Protect>} />
                  <Route path="/research" element={<Protect path="/research"><ResearchPage /></Protect>} />
                  <Route path="/research/:reportId" element={<Protect path="/research"><ResearchPage /></Protect>} />
                  <Route path="/documents" element={<Protect path="/documents"><DocumentsPage /></Protect>} />
                  <Route path="/knowledge-graph" element={<Protect path="/knowledge-graph"><KnowledgeGraphPage /></Protect>} />
                  <Route path="/compliance" element={<Protect path="/compliance"><CompliancePage /></Protect>} />
                  <Route path="/audit" element={<Protect path="/audit"><AuditPage /></Protect>} />
                  <Route path="/analytics" element={<Protect path="/analytics"><AnalyticsPage /></Protect>} />
                  <Route path="/settings" element={<Protect path="/settings"><SettingsPage /></Protect>} />
                  <Route path="/agents" element={<Protect path="/agents"><AgentsPage /></Protect>} />
                  <Route path="/admin" element={<Protect path="/admin"><AdminPage /></Protect>} />
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
