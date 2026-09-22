import { useEffect, useState } from "react";

/**
 * Viewport query hook (no resize listeners, no polling): a single
 * matchMedia subscription. SSR-safe default of false.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(query);
    setMatches(mql.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** Tailwind `lg` breakpoint and up (desktop shell). */
export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 1024px)");
}
