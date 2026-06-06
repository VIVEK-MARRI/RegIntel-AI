import { clsx } from "clsx";
import type { HTMLAttributes } from "react";

type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  dot?: boolean;
  size?: "sm" | "md";
}

const toneMap: Record<Tone, string> = {
  neutral: "badge-neutral",
  success: "badge-success",
  warning: "badge-warning",
  danger: "badge-danger",
  info: "badge-info",
  brand: "badge-brand",
};

const dotMap: Record<Tone, string> = {
  neutral: "bg-slate-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-red-500",
  info: "bg-sky-500",
  brand: "bg-brand-500",
};

export function Badge({
  tone = "neutral",
  dot = false,
  size = "md",
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={clsx(
        toneMap[tone],
        size === "sm" && "text-[10px] px-2 py-0.5",
        className
      )}
      {...rest}
    >
      {dot ? (
        <span
          aria-hidden
          className={clsx("h-1.5 w-1.5 rounded-full", dotMap[tone])}
        />
      ) : null}
      {children}
    </span>
  );
}
