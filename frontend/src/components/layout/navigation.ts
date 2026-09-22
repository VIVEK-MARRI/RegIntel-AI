/**
 * ONE source for navigation metadata. Sidebar, Topbar titles, and route
 * role-gates (App.tsx) all derive from here — never duplicated.
 *
 * Role semantics (UX only, never security): an item with `roles` is shown
 * iff `hasRole(...roles)`. Backend authorization remains authoritative;
 * hiding a link enforces nothing. Unknown roles fail safe (hidden).
 */
import type { KnownRole } from "@/providers/AuthProvider";

export interface NavItem {
  to: string;
  label: string;
  icon: string;
  /** Exact match only (used for "/"). */
  end?: boolean;
  /** Shown only when the session has at least one of these roles. */
  roles?: KnownRole[];
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "Dashboard", end: true },
  { to: "/copilot", label: "Copilot", icon: "Copilot" },
  { to: "/research", label: "Research", icon: "Research" },
  { to: "/documents", label: "Documents", icon: "Documents" },
  { to: "/knowledge-graph", label: "Knowledge Graph", icon: "Knowledge" },
  { to: "/compliance", label: "Compliance", icon: "Compliance" },
  { to: "/audit", label: "Audit", icon: "Audit" },
  { to: "/analytics", label: "Analytics", icon: "Analytics" },
  { to: "/settings", label: "Settings", icon: "Settings" },
];

export const ADMIN_NAV_ITEMS: NavItem[] = [
  // Parity with route guards: /agents admits admin/operator/analyst,
  // /admin admits admin. Links and guards derive from the same source.
  { to: "/agents", label: "AI Agents", icon: "Agents", roles: ["admin", "operator", "analyst"] },
  { to: "/admin", label: "Admin", icon: "Admin", roles: ["admin"] },
];

/** Route → required roles, consumed by App.tsx guards. */
export const ROUTE_ROLES: Record<string, KnownRole[]> = {
  "/agents": ["admin", "operator", "analyst"],
  "/admin": ["admin"],
};

export function visibleNavItems(
  items: NavItem[],
  hasRole: (...roles: string[]) => boolean
): NavItem[] {
  return items.filter((item) => !item.roles || hasRole(...item.roles));
}

export function titleForPath(path: string): string {
  if (path === "/") return "Dashboard";
  if (path.startsWith("/copilot")) return "Copilot";
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/documents")) return "Documents";
  if (path.startsWith("/knowledge-graph")) return "Knowledge Graph";
  if (path.startsWith("/compliance")) return "Compliance";
  if (path.startsWith("/audit")) return "Audit";
  if (path.startsWith("/analytics")) return "Analytics";
  if (path.startsWith("/settings")) return "Settings";
  if (path.startsWith("/agents")) return "AI Agents";
  if (path.startsWith("/admin")) return "Admin";
  return "RegIntel AI";
}
