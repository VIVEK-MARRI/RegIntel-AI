import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { HealthProvider } from "@/providers/HealthProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { AuthProvider } from "@/providers/AuthProvider";
import { App } from "@/App";
import "@/index.css";

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
                // Docker/nginx serves the SPA under /app; Render serves it
                // at the domain root. Override with VITE_BASENAME=/app for
                // docker-style deployments (default is already /app to
                // preserve current behaviour — set "/" for root serving).
                basename={import.meta.env.VITE_BASENAME ?? "/app"}
                future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
              >
              <AuthProvider>
                <App />
              </AuthProvider>
            </BrowserRouter>
          </HealthProvider>
        </ToastProvider>
      </ThemeProvider>
      <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
    </QueryClientProvider>
  </React.StrictMode>
);
