import { clsx } from "clsx";
import type { ReactNode } from "react";

interface MetricProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  delta?: { value: string; positive: boolean };
  className?: string;
  icon?: ReactNode;
}

export function Metric({ label, value, hint, delta, className, icon }: MetricProps) {
  return (
    <div className={clsx("card p-5", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {label}
        </p>
        {icon ? (
          <div
            aria-hidden
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-300"
          >
            {icon}
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
          {value}
        </p>
        {delta ? (
          <span
            className={clsx(
              "text-xs font-medium",
              delta.positive
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400"
            )}
          >
            {delta.value}
          </span>
        ) : null}
      </div>
      {hint ? (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      ) : null}
    </div>
  );
}
