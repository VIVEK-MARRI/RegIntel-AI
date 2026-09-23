import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark";
export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "regintel:theme";

function readPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  // Legacy installs stored an effective theme; keep it as an explicit choice.
  return "system";
}

function systemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveTheme(preference: ThemePreference): Theme {
  return preference === "system" ? systemTheme() : preference;
}

interface ThemeContextValue {
  /** Effective theme actually applied (never "system"). */
  theme: Theme;
  /** Stored preference, including "system" (follow the OS). */
  preference: ThemePreference;
  setTheme: (t: Theme) => void;
  setPreference: (p: ThemePreference) => void;
  toggle: () => void;
}

import { createContext, useContext } from "react";

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [theme, setThemeState] = useState<Theme>(() => resolveTheme(readPreference()));

  // Apply the effective theme, persist the preference, and follow OS changes
  // while the preference is "system".
  useEffect(() => {
    const apply = (t: Theme) => {
      const root = document.documentElement;
      root.classList.toggle("dark", t === "dark");
      root.setAttribute("data-theme", t);
      setThemeState(t);
    };
    apply(resolveTheme(preference));
    window.localStorage.setItem(STORAGE_KEY, preference);
    if (preference !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply(resolveTheme("system"));
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
    return undefined;
  }, [preference]);

  const setPreference = useCallback((p: ThemePreference) => setPreferenceState(p), []);
  // setTheme keeps its historical meaning: an explicit light/dark choice.
  const setTheme = useCallback((t: Theme) => setPreferenceState(t), []);
  const toggle = useCallback(
    () =>
      setPreferenceState((p) => {
        const effective = p === "system" ? systemTheme() : p;
        return effective === "dark" ? "light" : "dark";
      }),
    []
  );

  return (
    <ThemeContext.Provider value={{ theme, preference, setTheme, setPreference, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
