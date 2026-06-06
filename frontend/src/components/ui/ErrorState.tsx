import { clsx } from "clsx";
import type { ReactNode } from "react";

interface ErrorStateProps {
  title?: string;
  description?: string;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
  action?: ReactNode;
}

function extractMessage(error: unknown): string {
  if (!error) return "Something went wrong.";
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Unexpected error.";
}

export function ErrorState({
  title = "Unable to load",
  description,
  error,
  onRetry,
  className,
  action,
}: ErrorStateProps) {
  const msg = description ?? extractMessage(error);
  return (
    <div
      className={clsx(
        "rounded-2xl border border-red-200 bg-red-50/60 p-5 text-sm text-red-800",
        "dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-200",
        className
      )}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-full bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300"
        >
          !
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{title}</p>
          <p className="mt-1 text-xs leading-relaxed">{msg}</p>
        </div>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100 dark:border-red-800 dark:bg-red-950 dark:text-red-200 dark:hover:bg-red-900/40"
          >
            Retry
          </button>
        ) : null}
      </div>
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
