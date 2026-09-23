import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { Shell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RequireRole } from "@/components/auth/RequireRole";
import { AppErrorBoundary } from "@/components/ui/ErrorBoundary";
import { ROUTE_ROLES } from "@/components/layout/navigation";

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

function Protect({ path, children }: { path: string; children: React.ReactNode }) {
  // Role requirements derive from the same navigation config as the
  // sidebar links, so guards and visibility can never disagree.
  const roles = Object.entries(ROUTE_ROLES).find(([prefix]) =>
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
  const location = useLocation();
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route
          path="/*"
          element={
            <Suspense fallback={<PageFallback />}>
              <Shell>
                {/* Render crashes stay inside the shell: navigation survives. */}
                <AppErrorBoundary resetKey={location.pathname}>
                <Routes>
                  <Route path="/" element={<Protect path="/"><DashboardPage /></Protect>} />
                  <Route path="/copilot" element={<Protect path="/copilot"><CopilotPage /></Protect>} />
                  <Route path="/copilot/:conversationId" element={<Protect path="/copilot"><CopilotPage /></Protect>} />
                  <Route path="/research" element={<Protect path="/research"><ResearchPage /></Protect>} />
                  <Route path="/research/:reportId" element={<Protect path="/research"><ResearchPage /></Protect>} />
                  <Route path="/documents" element={<Protect path="/documents"><DocumentsPage /></Protect>} />
                  <Route path="/knowledge-graph" element={<Protect path="/knowledge-graph"><KnowledgeGraphPage /></Protect>} />
                  <Route path="/knowledge-graph/:nodeId" element={<Protect path="/knowledge-graph"><KnowledgeGraphPage /></Protect>} />
                  <Route path="/compliance" element={<Protect path="/compliance"><CompliancePage /></Protect>} />
                  <Route path="/audit" element={<Protect path="/audit"><AuditPage /></Protect>} />
                  <Route path="/analytics" element={<Protect path="/analytics"><AnalyticsPage /></Protect>} />
                  <Route path="/settings" element={<Protect path="/settings"><SettingsPage /></Protect>} />
                  <Route path="/agents" element={<Protect path="/agents"><AgentsPage /></Protect>} />
                  <Route path="/admin" element={<Protect path="/admin"><AdminPage /></Protect>} />
                  {/* Unknown paths respect auth too: logged-out users go to
                      login instead of seeing the shell around a 404. */}
                  <Route path="*" element={<Protect path="*"><NotFoundPage /></Protect>} />
                </Routes>
                </AppErrorBoundary>
              </Shell>
            </Suspense>
          }
        />
      </Routes>
    </Suspense>
  );
}
