import { clsx } from "clsx";
import type { HTMLAttributes, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

export function Table({
  className,
  caption,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { caption?: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table
        className={clsx(
          "w-full border-collapse text-left text-sm",
          "text-slate-700 dark:text-slate-200",
          className
        )}
        {...rest}
      >
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {rest.children}
      </table>
    </div>
  );
}

export function THead({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={clsx(
        "border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500",
        "dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400",
        className
      )}
      {...rest}
    />
  );
}

export function TBody({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody
      className={clsx("divide-y divide-slate-100 dark:divide-slate-800", className)}
      {...rest}
    />
  );
}

export function TR({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={clsx(
        "transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40",
        className
      )}
      {...rest}
    />
  );
}

export function TH({ className, scope = "col", ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope={scope}
      className={clsx("px-4 py-3 font-semibold", className)}
      {...rest}
    />
  );
}

export function TD({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={clsx("px-4 py-3 align-top", className)} {...rest} />;
}
