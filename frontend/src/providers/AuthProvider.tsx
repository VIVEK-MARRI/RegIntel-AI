/**
 * AuthProvider — the SINGLE owner of client authentication/session state.
 *
 * Explicit lifecycle (no ambiguous states):
 *
 *   unknown ── valid refresh + /me ──> authenticated
 *     │                                  │  ▲
 *     │ no token / refresh fails         │  │ login
 *     ▼                                  ▼  │
 *   unauthenticated ◄── logout / refresh failure / 401-exhausted
 *
 * While status is "unknown" (bootstrapping), ProtectedRoute renders a
 * spinner — protected pages NEVER render as authenticated prematurely, and
 * an ambiguous user-without-token state cannot exist (state transitions
 * set user + tokens + status atomically per generation).
 *
 * Threat model (honest, no fake security):
 * - The access token lives in memory only (lib/auth-token). The refresh
 *   token + cached user live in readable localStorage because the backend
 *   (app/security/api.py) issues bearer tokens with NO HttpOnly-cookie
 *   option. Any XSS can steal the refresh token — backend RBAC remains the
 *   ONLY authorization boundary; persisted roles are a CACHE and are
 *   replaced by server-validated roles on every bootstrap (refresh + /me).
 * - There is NO backend logout/revoke endpoint: logout is local-only and
 *   documented as such. A stolen refresh token stays valid server-side
 *   until it expires or rotates.
 * - The HTTP client (lib/api.ts) owns 401 detection + single-flight
 *   refresh orchestration; this provider owns tokens/session/scheduling.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as authApi from "@/services/api/authApi";
import type { AuthUser } from "@/types/api/auth";
import { getAccessToken, setAccessToken } from "@/lib/auth-token";
import { ApiClientError, getErrorMessage } from "@/lib/errors";
import { setAuthHandler } from "@/lib/api";

export type AuthStatus = "unknown" | "authenticated" | "unauthenticated";

/** Backend Role enum (app/security/rbac.py): the only known roles. */
export const KNOWN_ROLES = [
  "viewer",
  "analyst",
  "operator",
  "auditor",
  "admin",
  "service",
] as const;

export type KnownRole = (typeof KNOWN_ROLES)[number];

function isKnownRole(value: unknown): value is KnownRole {
  return (
    typeof value === "string" &&
    (KNOWN_ROLES as readonly string[]).includes(value.toLowerCase())
  );
}

/**
 * Normalize role input in EXACTLY ONE place. Unknown/malformed entries are
 * dropped (safe degrade); tampered localStorage can never mint a role the
 * server didn't grant because AUTHENTICATED requires fresh /me validation.
 */
export function normalizeRoles(input: unknown): KnownRole[] {
  const list = Array.isArray(input) ? input : [input];
  const out: KnownRole[] = [];
  for (const item of list) {
    if (isKnownRole(item)) {
      const role = item.toLowerCase() as KnownRole;
      if (!out.includes(role)) out.push(role);
    }
  }
  return out;
}

export type AuthAction = "login" | "signup" | "refresh" | "session";

/**
 * Map auth failures to safe, specific UI messages. Never leaks tokens,
 * stack traces, or backend internals.
 */
export function authErrorMessage(err: unknown, action: AuthAction): string {
  if (err instanceof ApiClientError) {
    if (err.code === "network" || err.code === "timeout") {
      return "Cannot reach the authentication server. Check your connection and try again.";
    }
    if (err.code === "aborted") {
      return "The request was cancelled. Please try again.";
    }
    switch (err.status) {
      case 400:
        return err.message || "Invalid request. Check the highlighted fields.";
      case 401:
        return action === "login"
          ? "Invalid email or password."
          : action === "refresh" || action === "session"
            ? "Your session has expired. Please sign in again."
            : "Authentication failed. Please try again.";
      case 403:
        return "Your account is not allowed to perform this action.";
      case 409:
        return err.message || "This account already exists.";
      case 422:
        return err.message || "Some fields are invalid. Check and try again.";
      case 429:
        return "Too many attempts. Wait a moment and try again.";
      case 500:
      case 502:
      case 503:
        return "The authentication service is unavailable. Try again shortly.";
      default:
        return err.message || "Authentication failed. Please try again.";
    }
  }
  return getErrorMessage(err, "Authentication failed. Please try again.");
}

/** Safe post-login redirect: same-origin app path only, never //evil. */
export function getSafeRedirect(raw: unknown): string {
  if (typeof raw !== "string" || !/^\/(?!\/)/.test(raw)) return "/";
  return raw;
}

export interface AuthState {
  user: AuthUser | null;
  /** Explicit lifecycle: unknown = bootstrapping, never render authed yet. */
  status: AuthStatus;
  /** Legacy alias for status === "unknown". Kept for guards/pages. */
  isLoading: boolean;
  isAuthenticated: boolean;
  /** True only for the explicit dev demo session (never silently). */
  demoMode: boolean;
  /** Last fatal auth notice (e.g. session expired, prod demo refused). */
  authError: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (...roles: string[]) => boolean;
  /** Explicit server revalidation (refresh + /me). Used by guards/tests. */
  refreshSession: () => Promise<boolean>;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY_REFRESH = "regintel_refresh_token";
const STORAGE_KEY_USER = "regintel_user";

/** Demo mode is OPT-IN ONLY: VITE_AUTH_ENABLED must literally be "false". */
function isDemoRequested(): boolean {
  return import.meta.env.VITE_AUTH_ENABLED === "false";
}

/**
 * Demo gate (pure, unit-tested): demo sessions are allowed in dev builds
 * only. Production builds FAIL CLOSED — an explicit demo flag is refused
 * and real authentication is required.
 */
export function resolveDemoAccess(
  demoRequested: boolean,
  isProduction: boolean
): "allow" | "deny" {
  if (!demoRequested) return "deny";
  return isProduction ? "deny" : "allow";
}

function persistRefreshToken(token: string | null) {
  if (token) localStorage.setItem(STORAGE_KEY_REFRESH, token);
  else localStorage.removeItem(STORAGE_KEY_REFRESH);
}

function persistUser(user: AuthUser | null) {
  if (user) {
    try {
      localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
    } catch {
      localStorage.removeItem(STORAGE_KEY_USER);
    }
  } else {
    localStorage.removeItem(STORAGE_KEY_USER);
  }
}

/** Defensive parse: malformed persisted sessions can never crash the app. */
function loadPersistedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_USER);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const u = parsed as Partial<AuthUser>;
    if (typeof u.user_id !== "string" || typeof u.email !== "string") return null;
    return {
      user_id: u.user_id,
      username: typeof u.username === "string" ? u.username : u.email,
      email: u.email,
      full_name: typeof u.full_name === "string" ? u.full_name : "",
      roles: Array.isArray(u.roles) ? u.roles.map(String) : [],
      rbac_roles: Array.isArray(u.rbac_roles) ? u.rbac_roles.map(String) : [],
    };
  } catch {
    return null;
  }
}

function loadPersistedRefreshToken(): string | null {
  const v = localStorage.getItem(STORAGE_KEY_REFRESH);
  return typeof v === "string" && v.length > 0 ? v : null;
}

function buildDemoUser(): AuthUser {
  return {
    user_id: "demo-user",
    username: "demo",
    email: "demo@regintel.ai",
    full_name: "Demo User",
    roles: ["admin", "analyst", "operator", "auditor"],
    rbac_roles: ["admin", "analyst", "operator", "auditor"],
  };
}

/** Shared in-flight bootstrap: defeats StrictMode double rotation. */
let bootstrapInflight: Promise<
  | { ok: true; refreshToken: string; accessToken: string; expiresIn: number; user: AuthUser }
  | { ok: false }
> | null = null;

async function runBootstrap(): Promise<
  | { ok: true; refreshToken: string; accessToken: string; expiresIn: number; user: AuthUser }
  | { ok: false }
> {
  const stored = loadPersistedRefreshToken();
  if (!stored) return { ok: false };
  try {
    const refreshed = await authApi.refreshToken(stored);
    // Memory first: /me requires the fresh Bearer token.
    setAccessToken(refreshed.access_token);
    persistRefreshToken(refreshed.refresh_token);
    let me;
    try {
      me = await authApi.getMe();
    } catch {
      // Bootstrap fails CLOSED: without server-validated identity, cached
      // roles must not mint a session.
      setAccessToken(null);
      persistRefreshToken(null);
      return { ok: false };
    }
    const cached = loadPersistedUser();
    const roles = normalizeRoles(me.roles);
    const user: AuthUser = {
      user_id: cached?.user_id ?? me.subject_id,
      username: cached?.username ?? me.subject_id,
      email: cached?.email ?? me.subject_id,
      full_name: cached?.full_name ?? "",
      roles,
      rbac_roles: roles,
    };
    return {
      ok: true,
      refreshToken: refreshed.refresh_token,
      accessToken: refreshed.access_token,
      expiresIn: refreshed.expires_in,
      user,
    };
  } catch {
    return { ok: false };
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("unknown");
  const [demoMode, setDemoMode] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [, setRefreshToken] = useState<string | null>(null);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const accessExpiresAt = useRef<number | null>(null);
  const rotateInflight = useRef<Promise<boolean> | null>(null);
  /** Generation: bumped on logout/login; stale async callbacks check it. */
  const generation = useRef(0);

  const clearTimer = useCallback(() => {
    if (refreshTimer.current) {
      clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    }
  }, []);

  const clearTokens = useCallback(() => {
    setAccessToken(null);
    setRefreshToken(null);
    persistRefreshToken(null);
    persistUser(null);
    setUser(null);
    accessExpiresAt.current = null;
  }, []);

  const scheduleRefreshRef = useRef((_expiresIn: number) => {});
  scheduleRefreshRef.current = useCallback(
    (expiresIn: number) => {
      clearTimer();
      accessExpiresAt.current = Date.now() + Math.max(0, expiresIn) * 1000;
      const ms = Math.max(10_000, (expiresIn - 30) * 1000);
      refreshTimer.current = setTimeout(() => {
        void rotateRef.current();
      }, ms);
    },
    [clearTimer]
  );

  const applySession = useCallback(
    (accessToken: string, nextRefresh: string, nextUser: AuthUser, expiresIn: number) => {
      const gen = generation.current;
      setAccessToken(accessToken);
      setRefreshToken(nextRefresh);
      persistRefreshToken(nextRefresh);
      setUser(nextUser);
      persistUser(nextUser);
      setDemoMode(false);
      setAuthError(null);
      setStatus("authenticated");
      scheduleRefreshRef.current(expiresIn);
      return gen;
    },
    []
  );

  /**
   * Single-flight rotation shared by timer, sleep-resume, and the 401
   * handler. Returns true when a fresh ACCESS token is in memory.
   * Ordering matters: the fresh access token is stored BEFORE /me, because
   * /me itself requires Bearer auth.
   */
  const rotate = useCallback(async (): Promise<boolean> => {
    if (rotateInflight.current) return rotateInflight.current;
    const gen = generation.current;
    const work = (async (): Promise<boolean> => {
      const stored = loadPersistedRefreshToken();
      if (!stored) {
        if (generation.current === gen) clearTokens();
        return false;
      }
      try {
        const res = await authApi.refreshToken(stored);
        if (generation.current !== gen) return false;
        setAccessToken(res.access_token);
        setRefreshToken(res.refresh_token);
        persistRefreshToken(res.refresh_token);
        try {
          const me = await authApi.getMe();
          if (generation.current !== gen) return false;
          const roles = normalizeRoles(me.roles);
          const cached = loadPersistedUser();
          applySession(
            res.access_token,
            res.refresh_token,
            {
              user_id: cached?.user_id ?? me.subject_id,
              username: cached?.username ?? me.subject_id,
              email: cached?.email ?? me.subject_id,
              full_name: cached?.full_name ?? "",
              roles,
              rbac_roles: roles,
            },
            res.expires_in
          );
        } catch {
          // Revalidation failed but rotation succeeded: keep the fresh
          // tokens with the cached identity when one exists (session stays
          // alive; roles refresh on the next success). Bootstrap never
          // reaches here — it fails closed instead (see runBootstrap).
          const cached = loadPersistedUser();
          if (!cached) {
            if (generation.current === gen) clearTokens();
            return false;
          }
          const roles = normalizeRoles([...cached.roles, ...cached.rbac_roles]);
          applySession(
            res.access_token,
            res.refresh_token,
            { ...cached, roles, rbac_roles: roles },
            res.expires_in
          );
        }
        return true;
      } catch {
        if (generation.current === gen) {
          clearTokens();
          setStatus("unauthenticated");
        }
        return false;
      }
    })();
    rotateInflight.current = work;
    try {
      return await work;
    } finally {
      if (rotateInflight.current === work) rotateInflight.current = null;
    }
  }, [applySession, clearTokens]);

  const rotateRef = useRef(rotate);
  rotateRef.current = rotate;

  // Browser sleep/tab-suspend: timers may have died while tokens expired.
  // On visible, rotate when the access token is past (or near) expiry.
  useEffect(() => {
    const onVisible = () => {
      if (document.hidden) return;
      if (status !== "authenticated" || demoMode) return;
      if (accessExpiresAt.current === null) return;
      if (Date.now() > accessExpiresAt.current - 60_000) {
        void rotateRef.current();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [status, demoMode]);

  // ---- bootstrap (mount once; shared across StrictMode remounts) ----
  useEffect(() => {
    const myGen = generation.current;
    let cancelled = false;
    if (isDemoRequested()) {
      if (resolveDemoAccess(true, import.meta.env.PROD) === "deny") {
        // FAIL CLOSED: an explicit demo flag in a production build refuses
        // the synthetic session and requires real authentication.
        // eslint-disable-next-line no-console
        console.error(
          "[auth] Demo mode requested in a production build — refusing. " +
            "Sign in with a real account."
        );
        setStatus("unauthenticated");
        setAuthError("Demo mode is disabled in production. Please sign in.");
        return;
      }
      // eslint-disable-next-line no-console
      console.warn(
        "[auth] DEMO MODE active (VITE_AUTH_ENABLED=false, dev build): " +
          "synthetic all-roles session, Bearer demo. Never ship this flag."
      );
      const demo = buildDemoUser();
      setUser(demo);
      persistUser(demo);
      setRefreshToken("demo");
      setAccessToken("demo");
      setDemoMode(true);
      setStatus("authenticated");
      return;
    }
    if (!bootstrapInflight) {
      bootstrapInflight = runBootstrap().finally(() => {
        bootstrapInflight = null;
      });
    }
    void bootstrapInflight.then((result) => {
      if (cancelled || generation.current !== myGen) return;
      if (result.ok) {
        applySession(
          result.accessToken,
          result.refreshToken,
          result.user,
          result.expiresIn
        );
      } else {
        clearTokens();
        setStatus("unauthenticated");
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // HTTP-client boundary: single-flight 401 → rotation → retry-once.
  useEffect(() => {
    setAuthHandler({
      getAccessToken: () => getAccessToken(),
      refreshAccessToken: () => rotateRef.current(),
      onAuthFailure: () => {
        generation.current++;
        clearTimer();
        clearTokens();
        setStatus("unauthenticated");
        setAuthError("Your session has expired. Please sign in again.");
        queryClient.clear();
      },
    });
    return () => {
      setAuthHandler(null);
      clearTimer();
    };
  }, [clearTimer, clearTokens, queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      const cleanEmail = email.trim().toLowerCase();
      if (!cleanEmail || !password) {
        throw new Error("Email and password are required.");
      }
      generation.current++;
      const res = await authApi.login({ email: cleanEmail, password });
      const roles = normalizeRoles([...res.user.roles, ...res.user.rbac_roles]);
      // A different identity must never inherit the previous cache.
      queryClient.clear();
      applySession(res.access_token, res.refresh_token, {
        ...res.user,
        roles,
        rbac_roles: roles,
      }, res.expires_in);
    },
    [applySession, queryClient]
  );

  const logout = useCallback(() => {
    if (demoMode) return; // nothing real to terminate in demo mode
    generation.current++;
    bootstrapInflight = null;
    clearTimer();
    clearTokens();
    setDemoMode(false);
    setAuthError(null);
    setStatus("unauthenticated");
    // Drop every cached server response so the next identity starts clean.
    // In-flight queries were issued under the old session; cancelling then
    // clearing prevents User B from ever seeing User A's data.
    void queryClient.cancelQueries().catch(() => undefined).finally(() => {
      queryClient.clear();
    });
  }, [clearTimer, clearTokens, demoMode, queryClient]);

  const hasRole = useCallback(
    (...roles: string[]) => {
      if (demoMode) return true;
      if (status !== "authenticated" || !user) return false;
      const mine = new Set(normalizeRoles([...user.roles, ...user.rbac_roles]));
      return roles.some((r) => mine.has(r.toLowerCase() as KnownRole));
    },
    [demoMode, status, user]
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      status,
      isLoading: status === "unknown",
      isAuthenticated: status === "authenticated",
      demoMode,
      authError,
      login,
      logout,
      hasRole,
      refreshSession: () => rotateRef.current(),
    }),
    [user, status, demoMode, authError, login, logout, hasRole]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}