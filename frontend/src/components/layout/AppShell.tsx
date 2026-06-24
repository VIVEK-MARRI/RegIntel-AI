import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { useTheme } from "@/providers/ThemeProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useState, type ReactNode } from "react";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  minRole?: string;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "Dashboard" },
  { to: "/copilot", label: "Copilot", icon: "Copilot" },
  { to: "/research", label: "Research", icon: "Research" },
  { to: "/documents", label: "Documents", icon: "Documents" },
  { to: "/knowledge-graph", label: "Knowledge Graph", icon: "Knowledge" },
  { to: "/compliance", label: "Compliance", icon: "Compliance" },
  { to: "/audit", label: "Audit", icon: "Audit" },
  { to: "/analytics", label: "Analytics", icon: "Analytics" },
  { to: "/settings", label: "Settings", icon: "Settings" },
];

const AGENT_ITEM: NavItem = { to: "/agents", label: "AI Agents", icon: "Agents", minRole: "admin" };
const ADMIN_ITEM: NavItem = { to: "/admin", label: "Admin", icon: "Admin", minRole: "admin" };

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  const { theme, toggle } = useTheme();
  const { hasRole } = useAuth();

  const items = NAV.filter((n) => !n.minRole || hasRole(n.minRole));

  const extraItems = [AGENT_ITEM, ADMIN_ITEM].filter(
    (n) => !n.minRole || hasRole(n.minRole)
  );

  return (
    <aside
      className={clsx(
        "flex h-full shrink-0 flex-col border-r border-slate-200 bg-white transition-all duration-200",
        "dark:border-slate-800 dark:bg-surface-dark-2",
        collapsed ? "w-16" : "w-64"
      )}
      aria-label="Primary navigation"
    >
      <div className="flex h-14 items-center gap-2 border-b border-slate-200 px-4 dark:border-slate-800">
        <div
          aria-hidden
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow"
        >
          R
        </div>
        {!collapsed ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              RegIntel AI
            </p>
            <p className="truncate text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Regulatory Intelligence
            </p>
          </div>
        ) : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-0.5">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  clsx("nav-link", isActive && "nav-link-active")
                }
                title={collapsed ? item.label : undefined}
              >
                <NavIcon name={item.icon} />
                {!collapsed ? <span className="truncate">{item.label}</span> : null}
              </NavLink>
            </li>
          ))}
        </ul>
        {extraItems.length > 0 && (
          <>
            <hr className="my-3 border-slate-200 dark:border-slate-700" />
            <ul className="space-y-0.5">
              {extraItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      clsx("nav-link", isActive && "nav-link-active")
                    }
                    title={collapsed ? item.label : undefined}
                  >
                    <NavIcon name={item.icon} />
                    {!collapsed ? <span className="truncate">{item.label}</span> : null}
                  </NavLink>
                </li>
              ))}
            </ul>
          </>
        )}
      </nav>

      <div className="border-t border-slate-200 p-2 dark:border-slate-800">
        <button
          type="button"
          onClick={toggle}
          className="nav-link w-full justify-start"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          <span aria-hidden>{theme === "dark" ? "Light" : "Dark"}</span>
          {!collapsed ? <span className="truncate ml-2">{theme === "dark" ? "Light" : "Dark"} mode</span> : null}
        </button>
      </div>
    </aside>
  );
}

function NavIcon({ name }: { name: string }) {
  const icons: Record<string, ReactNode> = {
    Dashboard: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>,
    Copilot: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
    Research: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>,
    Documents: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>,
    Knowledge: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M21 12a9 9 0 0 0-9-9 9 9 0 0 0-9 9 9 9 0 0 0 9 9 9 9 0 0 0 9-9z"/><circle cx="12" cy="12" r="0.5" fill="currentColor"/></svg>,
    Compliance: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>,
    Audit: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>,
    Analytics: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>,
    Settings: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
    Agents: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
    Admin: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  };
  return <span aria-hidden className="shrink-0">{icons[name] ?? name}</span>;
}

export function Topbar({ onToggleSidebar }: TopbarProps) {
  const location = useLocation();
  const title = titleForPath(location.pathname);
  return (
    <header
      className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur
                 dark:border-slate-800 dark:bg-surface-dark-2/80"
    >
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-label="Toggle sidebar"
        className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
        {title}
      </h1>
      <div className="flex-1" />
      <SystemStatusPill />
      <UserMenu />
    </header>
  );
}

interface TopbarProps { onToggleSidebar: () => void }

function SystemStatusPill() {
  return (
    <div
      className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 sm:flex
                 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300"
      role="status"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      <span>All systems operational</span>
    </div>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const initials = user?.full_name
    ? user.full_name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : user?.username?.slice(0, 2).toUpperCase() || "?";

  const displayName = user?.full_name || user?.username || "User";

  const handleSignOut = () => {
    setOpen(false);
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-50
                   dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-200 dark:hover:bg-slate-800"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-[10px] font-semibold text-white">
          {initials}
        </span>
        <span className="hidden sm:inline">{displayName}</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-9 z-20 w-44 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 text-xs shadow-elevated
                     dark:border-slate-700 dark:bg-surface-dark-2"
        >
          {["Profile", "API Keys", "Activity Log"].map((label) => (
            <button
              key={label}
              type="button"
              role="menuitem"
              className="block w-full px-3 py-2 text-left text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
              onClick={() => setOpen(false)}
            >
              {label}
            </button>
          ))}
          {import.meta.env.VITE_AUTH_ENABLED !== "false" ? (
            <>
              <div className="border-t border-slate-200 dark:border-slate-700" />
              <button
                type="button"
                role="menuitem"
                className="block w-full px-3 py-2 text-left text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
                onClick={handleSignOut}
              >
                Sign out
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function titleForPath(path: string): string {
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
