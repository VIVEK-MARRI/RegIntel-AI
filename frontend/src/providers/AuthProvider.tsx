import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as authApi from "@/services/api/authApi";
import { setAccessToken } from "@/lib/auth-token";

type User = authApi.LoginResponse["user"];

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (...roles: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY_REFRESH = "regintel_refresh_token";
const STORAGE_KEY_USER = "regintel_user";

function persistRefreshToken(token: string | null) {
  if (token) {
    localStorage.setItem(STORAGE_KEY_REFRESH, token);
  } else {
    localStorage.removeItem(STORAGE_KEY_REFRESH);
  }
}

function persistUser(user: User | null) {
  if (user) {
    localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
  } else {
    localStorage.removeItem(STORAGE_KEY_USER);
  }
}

function loadPersistedUser(): User | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_USER);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function loadPersistedRefreshToken(): string | null {
  return localStorage.getItem(STORAGE_KEY_REFRESH);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(loadPersistedUser);
  const [refreshToken, setRefreshToken] = useState<string | null>(
    loadPersistedRefreshToken
  );
  const [isLoading, setIsLoading] = useState(true);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTokens = useCallback(() => {
    setAccessToken(null);
    setRefreshToken(null);
    persistRefreshToken(null);
    persistUser(null);
    setUser(null);
  }, []);

  const performRefresh = useCallback(async () => {
    const stored = loadPersistedRefreshToken();
    if (!stored) {
      clearTokens();
      return;
    }
    try {
      const res = await authApi.refreshToken(stored);
      setAccessToken(res.access_token);
      setRefreshToken(res.refresh_token);
      persistRefreshToken(res.refresh_token);
      if (res.user) {
        setUser(res.user);
        persistUser(res.user);
      }
      scheduleRefresh(res.expires_in);
    } catch {
      clearTokens();
    }
  }, [clearTokens]);

  const scheduleRefresh = useCallback(
    (expiresIn: number) => {
      if (refreshTimer.current) {
        clearTimeout(refreshTimer.current);
      }
      const ms = Math.max(10000, (expiresIn - 30) * 1000);
      refreshTimer.current = setTimeout(() => {
        performRefresh();
      }, ms);
    },
    [performRefresh]
  );

  // Define performRefresh after scheduleRefresh ref, but before use
  // Actually we need to restructure to avoid circular refs
  const performRefreshRef = useRef(performRefresh);
  performRefreshRef.current = performRefresh;

  const scheduleRefreshRef = useCallback(
    (expiresIn: number) => {
      if (refreshTimer.current) {
        clearTimeout(refreshTimer.current);
      }
      const ms = Math.max(10000, (expiresIn - 30) * 1000);
      refreshTimer.current = setTimeout(() => {
        performRefreshRef.current();
      }, ms);
    },
    []
  );

  // Bootstrap on mount
  useEffect(() => {
    const init = async () => {
      const storedRefresh = loadPersistedRefreshToken();
      if (storedRefresh) {
        try {
          const res = await authApi.refreshToken(storedRefresh);
          setAccessToken(res.access_token);
          setRefreshToken(res.refresh_token);
          persistRefreshToken(res.refresh_token);
          if (res.user) {
            setUser(res.user);
            persistUser(res.user);
          }
          scheduleRefreshRef(res.expires_in);
        } catch {
          clearTokens();
        }
      }
      setIsLoading(false);
    };
    init();
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await authApi.login({ email, password });
      setAccessToken(res.access_token);
      setRefreshToken(res.refresh_token);
      persistRefreshToken(res.refresh_token);
      setUser(res.user);
      persistUser(res.user);
      scheduleRefreshRef(res.expires_in);
    },
    [scheduleRefreshRef]
  );

  const logout = useCallback(() => {
    clearTokens();
    if (refreshTimer.current) {
      clearTimeout(refreshTimer.current);
    }
  }, [clearTokens]);

  const hasRole = useCallback(
    (...roles: string[]) => {
      if (!user) return false;
      return roles.some((r) => user.rbac_roles.includes(r));
    },
    [user]
  );

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: !!user && !!refreshToken,
      isLoading,
      login,
      logout,
      hasRole,
    }),
    [user, refreshToken, isLoading, login, logout, hasRole]
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
