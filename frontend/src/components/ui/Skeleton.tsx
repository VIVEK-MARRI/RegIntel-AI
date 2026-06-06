import { clsx } from "clsx";

interface SkeletonProps {
  className?: string;
  /** Approximate width/height in tailwind classes if not provided via className. */
  lines?: number;
}

export function Skeleton({ className, lines = 1 }: SkeletonProps) {
  if (lines > 1) {
    return (
      <div className="space-y-2" aria-busy>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={clsx(
              "skeleton h-3",
              i === lines - 1 ? "w-2/3" : "w-full",
              className
            )}
          />
        ))}
      </div>
    );
  }
  return <div className={clsx("skeleton h-3 w-full", className)} aria-busy />;
}
