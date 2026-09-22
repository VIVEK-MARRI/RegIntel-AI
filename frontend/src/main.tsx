import React, { Suspense } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { HealthProvider } from "@/providers/HealthProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { AuthProvider } from "@/providers/AuthProvider";
import { ROUTER_BASE } from "@/lib/config";
import { App } from "@/App";
import "@/index.css";

// React Query Devtools are development-only: lazy-loaded and never part
// of the production bundle.
const Devtools =
  import.meta.env.DEV
    ? React.lazy(() =>
        import("@tanstack/react-query-devtools").then((m) => ({
          default: m.ReactQueryDevtools,
        }))
      )
    : null;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <HealthProvider>
              <BrowserRouter
                // Router base ownership lives in lib/config (ROUTER_BASE).
                // Docker/nginx serves the SPA under /app; Render serves it
                // at the domain root. Must agree with the build base
                // (SPA_BASE in vite.config.ts) — see lib/config.ts.
                basename={ROUTER_BASE}
                future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
              >
              <AuthProvider>
                <App />
              </AuthProvider>
            </BrowserRouter>
          </HealthProvider>
        </ToastProvider>
      </ThemeProvider>
      {Devtools ? (
        <Suspense fallback={null}>
          <Devtools initialIsOpen={false} buttonPosition="bottom-left" />
        </Suspense>
      ) : null}
    </QueryClientProvider>
  </React.StrictMode>
);
