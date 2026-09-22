import { Children, cloneElement, isValidElement, useId } from "react";
import { clsx } from "clsx";
import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, ReactNode } from "react";

interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
  id?: string;
}

export function Field({ label, hint, error, required, className, children, id }: FieldProps) {
  const autoId = useId();
  const baseId = id ?? autoId;
  const errorId = `${baseId}-error`;
  const hintId = `${baseId}-hint`;

  // Link the control to its error/hint for assistive tech. Only a single
  // element child is enhanced; anything else renders untouched.
  const kids = Children.toArray(children);
  const enhanced =
    kids.length === 1 && isValidElement<Record<string, unknown>>(kids[0])
      ? cloneElement(kids[0], {
          ...(error
            ? { "aria-invalid": true, "aria-describedby": errorId }
            : hint
              ? { "aria-describedby": hintId }
              : null),
        })
      : children;

  return (
    <div className={clsx("flex flex-col gap-1.5", className)}>
      {label ? (
        <label
          htmlFor={id}
          className="text-xs font-semibold text-slate-700 dark:text-slate-300"
        >
          {label}
          {required ? <span className="ml-0.5 text-red-500" aria-hidden> *</span> : null}
          {required ? <span className="sr-only"> (required)</span> : null}
        </label>
      ) : null}
      {enhanced}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      ) : null}
    </div>
  );
}

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx("input", className)} {...rest} />;
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx("input min-h-[88px] resize-y", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx("input pr-8", className)} {...rest}>
      {children}
    </select>
  );
}
