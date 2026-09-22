import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => ({
  // Sub-path serving: the SPA lives under /app (FastAPI-embedded and
  // nginx both serve it there). Override with SPA_BASE=/ for root
  // serving (e.g. Render static site via render.yaml).
  // NOTE: must agree with the router base (VITE_BASENAME, owned by
  // src/lib/config.ts) — setting only one breaks either routes or assets.
  base: process.env.SPA_BASE ?? "/app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Dev only. Production traffic must never depend on these targets:
    // same-origin reverse proxy or baked VITE_API_BASE_URL instead.
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    // Sourcemaps ship original TS sources to every browser — useful for
    // local debugging, an info leak in a public bundle. Gated on Vite
    // mode (not NODE_ENV): `vite build` defaults to production mode, so
    // release bundles never include sources regardless of environment.
    sourcemap: mode !== "production",
  },
}));
