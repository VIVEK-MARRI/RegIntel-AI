import { useAuth } from "@/providers/AuthProvider";
import type { ReactNode } from "react";

interface RequireRoleProps {
  roles: string[];
  children: ReactNode;
  fallback?: ReactNode;
}

export function RequireRole({ roles, children, fallback }: RequireRoleProps) {
  const { hasRole, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  if (!hasRole(...roles)) {
    if (fallback) {
      return <>{fallback}</>;
    }
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="text-4xl text-slate-300 dark:text-slate-600">🔒</div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Access restricted
        </h2>
        <p className="max-w-sm text-xs text-slate-500 dark:text-slate-400">
          You do not have the required role to access this page. Contact your
          administrator if you need access.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
