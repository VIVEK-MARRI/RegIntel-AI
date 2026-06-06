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
  return (
    <div className={clsx("flex flex-col gap-1.5", className)}>
      {label ? (
        <label
          htmlFor={id}
          className="text-xs font-semibold text-slate-700 dark:text-slate-300"
        >
          {label}
          {required ? <span className="ml-0.5 text-red-500">*</span> : null}
        </label>
      ) : null}
      {children}
      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : hint ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
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
