import { clsx } from "clsx";

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  tone?: "brand" | "success" | "warning" | "danger";
  showLabel?: boolean;
}

const toneMap = {
  brand: "bg-brand-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-red-500",
} as const;

export function ProgressBar({
  value,
  max = 100,
  className,
  tone = "brand",
  showLabel = false,
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, (value / Math.max(1, max)) * 100));
  return (
    <div className={clsx("w-full", className)}>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
      >
        <div
          className={clsx("h-full rounded-full transition-all duration-500", toneMap[tone])}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel ? (
        <p className="mt-1 text-right text-[10px] text-slate-500 dark:text-slate-400">
          {pct.toFixed(0)}%
        </p>
      ) : null}
    </div>
  );
}
