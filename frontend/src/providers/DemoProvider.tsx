import { createContext, useContext, useState, useCallback, useMemo } from "react";

export interface DemoFallbackState {
  activeWorkspaces: Set<string>;
  add: (workspace: string) => void;
  remove: (workspace: string) => void;
  clear: () => void;
  hasAny: boolean;
}

const DemoContext = createContext<DemoFallbackState | null>(null);

export function DemoProvider({ children }: { children: React.ReactNode }) {
  const [activeWorkspaces, setActiveWorkspaces] = useState<Set<string>>(new Set());

  const add = useCallback((workspace: string) => {
    setActiveWorkspaces((prev) => {
      if (prev.has(workspace)) return prev;
      const next = new Set(prev);
      next.add(workspace);
      return next;
    });
  }, []);

  const remove = useCallback((workspace: string) => {
    setActiveWorkspaces((prev) => {
      if (!prev.has(workspace)) return prev;
      const next = new Set(prev);
      next.delete(workspace);
      return next;
    });
  }, []);

  const clear = useCallback(() => setActiveWorkspaces(new Set()), []);

  const value = useMemo(
    () => ({
      activeWorkspaces,
      add,
      remove,
      clear,
      hasAny: activeWorkspaces.size > 0,
    }),
    [activeWorkspaces, add, remove, clear],
  );

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemoContext(): DemoFallbackState {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemoContext must be used within DemoProvider");
  return ctx;
}
