/**
 * Single ownership model for frontend configuration.
 *
 * - ROUTER BASE (`VITE_BASENAME`, default "/app"): where the SPA routes live.
 *   Consumed ONLY by BrowserRouter basename (main.tsx).
 * - STATIC BUILD BASE (`SPA_BASE`, default "/app/"): where Vite emits asset
 *   URLs. Consumed ONLY by vite.config.ts. These two must agree on the
 *   deploy layout (both "/app*" for embedded/Blueprint, both "/" for
 *   root-served static); they are separate vars because one is a router
 *   concept and the other a build concept.
 * - API BASE (`VITE_API_BASE_URL`, default ""): backend origin. Empty means
 *   same-origin (Vite dev proxy / reverse proxy). Baked at build time —
 *   there is NO runtime API-base configuration (Settings cannot change it).
 *
 * VITE_* values are bundled into the JS assets: never put secrets here.
 */
function stripTrailingSlash(v: string): string {
  return v.replace(/\/$/, "");
}

export const ROUTER_BASE = stripTrailingSlash(
  import.meta.env.VITE_BASENAME ?? "/app"
) || "/";

export const API_BASE_URL = stripTrailingSlash(
  import.meta.env.VITE_API_BASE_URL ?? ""
);

export const API_PREFIX = "/api/v1";

export const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED !== "false";

export const appConfig = {
  routerBase: ROUTER_BASE,
  apiBaseUrl: API_BASE_URL,
  apiPrefix: API_PREFIX,
  authEnabled: AUTH_ENABLED,
} as const;
