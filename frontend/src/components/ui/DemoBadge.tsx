import { useDemoContext } from "@/providers/DemoProvider";

export function DemoBadge() {
  const { activeWorkspaces, hasAny } = useDemoContext();

  if (!hasAny) return null;

  const workspaceList = Array.from(activeWorkspaces).join(", ");

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700
                 dark:border-amber-700/50 dark:bg-amber-950/40 dark:text-amber-300"
      role="status"
      title={`Demo data active for: ${workspaceList}`}
    >
      <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
      <span>Showing Demo Data</span>
    </div>
  );
}
