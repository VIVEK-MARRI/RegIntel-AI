import { useEffect } from "react";
import { useToast } from "@/providers/ToastProvider";
import { clsx } from "clsx";

const toneStyles = {
  info: "border-sky-200 bg-white text-sky-900 dark:border-sky-900/40 dark:bg-surface-dark-2 dark:text-sky-200",
  success:
    "border-emerald-200 bg-white text-emerald-900 dark:border-emerald-900/40 dark:bg-surface-dark-2 dark:text-emerald-200",
  warning:
    "border-amber-200 bg-white text-amber-900 dark:border-amber-900/40 dark:bg-surface-dark-2 dark:text-amber-200",
  danger:
    "border-red-200 bg-white text-red-900 dark:border-red-900/40 dark:bg-surface-dark-2 dark:text-red-200",
};

export function ToastViewport() {
  const { toasts, dismiss } = useToast();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && toasts.length) dismiss(toasts[toasts.length - 1].id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toasts, dismiss]);

  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            "pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-elevated",
            toneStyles[t.tone]
          )}
          role="status"
        >
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{t.title}</p>
              {t.description ? (
                <p className="mt-0.5 text-xs leading-relaxed opacity-80">
                  {t.description}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              className="rounded p-1 opacity-60 transition hover:opacity-100"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
