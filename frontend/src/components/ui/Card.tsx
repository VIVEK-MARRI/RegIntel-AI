import { clsx } from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: "none" | "sm" | "md" | "lg";
  interactive?: boolean;
}

export function Card({
  className,
  padding = "none",
  interactive = false,
  children,
  ...rest
}: CardProps) {
  const padCls =
    padding === "sm"
      ? "p-3"
      : padding === "md"
        ? "p-5"
        : padding === "lg"
          ? "p-6"
          : "";
  return (
    <div
      className={clsx(
        "card",
        padCls,
        interactive &&
          "transition hover:shadow-glow cursor-pointer focus-within:shadow-glow",
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

export function CardHeader({
  title,
  description,
  actions,
  className,
  ...rest
}: CardHeaderProps) {
  return (
    <div className={clsx("card-header", className)} {...rest}>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h3>
        {description ? (
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("card-body", className)} {...rest} />;
}
