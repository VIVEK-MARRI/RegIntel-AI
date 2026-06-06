import { clsx } from "clsx";
import type { ReactNode } from "react";

type Tone = "info" | "success" | "warning" | "danger";

interface AlertProps {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  className?: string;
  onDismiss?: () => void;
}

const toneMap: Record<Tone, string> = {
  info: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200",
  success:
    "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200",
  warning:
    "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200",
  danger:
    "border-red-200 bg-red-50 text-red-900 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-200",
};

export function Alert({ tone = "info", title, children, className, onDismiss }: AlertProps) {
  return (
    <div
      className={clsx(
        "flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm",
        toneMap[tone],
        className
      )}
      role="status"
    >
      <div className="min-w-0 flex-1">
        {title ? <p className="text-sm font-semibold">{title}</p> : null}
        {children ? <div className="mt-0.5 text-xs leading-relaxed">{children}</div> : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="rounded p-1 text-current opacity-60 transition hover:bg-black/5 hover:opacity-100 dark:hover:bg-white/10"
        >
          ×
        </button>
      ) : null}
    </div>
  );
}
