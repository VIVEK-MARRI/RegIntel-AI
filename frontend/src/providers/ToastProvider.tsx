import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  tone: ToastTone;
  durationMs?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let counter = 0;
const newId = () => `tst-${Date.now().toString(36)}-${++counter}`;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((list) => list.filter((t) => t.id !== id));
    const handle = timers.current.get(id);
    if (handle) {
      clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = newId();
      const defaults: Pick<Toast, "tone" | "durationMs"> = {
        tone: "info",
        durationMs: 4500,
      };
      const entry: Toast = { ...defaults, ...toast, id };
      setToasts((list) => [...list, entry]);
      if ((entry.durationMs ?? 0) > 0) {
        const handle = setTimeout(() => dismiss(id), entry.durationMs);
        timers.current.set(id, handle);
      }
      return id;
    },
    [dismiss]
  );

  const clear = useCallback(() => {
    timers.current.forEach((handle) => clearTimeout(handle));
    timers.current.clear();
    setToasts([]);
  }, []);

  const value = useMemo(
    () => ({ toasts, push, dismiss, clear }),
    [toasts, push, dismiss, clear]
  );

  return (
    <ToastContext.Provider value={value}>{children}</ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
