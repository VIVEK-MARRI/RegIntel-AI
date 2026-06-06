import { NavLink, useLocation } from "react-router-dom";
import { clsx } from "clsx";
import { useTheme } from "@/providers/ThemeProvider";
import { useState } from "react";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  group: "main" | "agents" | "platform";
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "▦", group: "main" },
  { to: "/copilot", label: "Copilot", icon: "✦", group: "main" },
  { to: "/research", label: "Research", icon: "⌕", group: "main" },
  { to: "/compliance", label: "Compliance", icon: "✓", group: "main" },
  { to: "/risk", label: "Risk", icon: "△", group: "main" },
  { to: "/knowledge-graph", label: "Knowledge Graph", icon: "◌", group: "main" },
  { to: "/agents", label: "Agent Control Center", icon: "◍", group: "agents" },
  { to: "/agents/collaboration", label: "Collaboration", icon: "↔", group: "agents" },
  { to: "/agents/health", label: "Agent Health", icon: "♥", group: "agents" },
  { to: "/agents/workflows", label: "Agent Workflows", icon: "↧", group: "agents" },
  { to: "/governance", label: "Governance", icon: "§", group: "platform" },
  { to: "/audit", label: "Audit", icon: "⛬", group: "platform" },
  { to: "/admin", label: "Admin", icon: "☰", group: "platform" },
  { to: "/settings", label: "Settings", icon: "⚙", group: "platform" },
];

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  const { theme, toggle } = useTheme();
  const groups: Array<{ key: NavItem["group"]; title: string }> = [
    { key: "main", title: "Workspace" },
    { key: "agents", title: "Agent Control Center" },
    { key: "platform", title: "Platform" },
  ];

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
          ⌬
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
        {groups.map((g) => {
          const items = NAV.filter((n) => n.group === g.key);
          if (!items.length) return null;
          return (
            <div key={g.key} className="mb-4">
              {!collapsed ? (
                <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                  {g.title}
                </p>
              ) : null}
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
                      <span aria-hidden className="text-base">
                        {item.icon}
                      </span>
                      {!collapsed ? <span className="truncate">{item.label}</span> : null}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-slate-200 p-2 dark:border-slate-800">
        <button
          type="button"
          onClick={toggle}
          className="nav-link w-full justify-start"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span>
          {!collapsed ? (
            <span className="truncate">
              {theme === "dark" ? "Light" : "Dark"} mode
            </span>
          ) : null}
        </button>
      </div>
    </aside>
  );
}

interface TopbarProps {
  onToggleSidebar: () => void;
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
        ☰
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

function SystemStatusPill() {
  return (
    <div
      className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 sm:flex
                 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300"
      role="status"
    >
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-emerald-500" />
      <span>All systems operational</span>
    </div>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
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
          VK
        </span>
        <span className="hidden sm:inline">Vivek K.</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-9 z-20 w-44 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 text-xs shadow-elevated
                     dark:border-slate-700 dark:bg-surface-dark-2"
        >
          {["Profile", "API Keys", "Activity Log", "Sign out"].map((label) => (
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
        </div>
      ) : null}
    </div>
  );
}

function titleForPath(path: string): string {
  if (path === "/") return "Dashboard";
  if (path.startsWith("/copilot")) return "Copilot Workspace";
  if (path.startsWith("/research")) return "Research Workspace";
  if (path.startsWith("/compliance")) return "Compliance Workspace";
  if (path.startsWith("/risk")) return "Risk Workspace";
  if (path.startsWith("/knowledge-graph")) return "Knowledge Graph Explorer";
  if (path === "/agents") return "Agent Control Center";
  if (path.startsWith("/agents/collaboration")) return "Agent Collaboration";
  if (path.startsWith("/agents/health")) return "Agent Health";
  if (path.startsWith("/agents/workflows")) return "Agent Workflows";
  if (path.startsWith("/governance")) return "Governance Center";
  if (path.startsWith("/audit")) return "Audit Console";
  if (path.startsWith("/admin")) return "Admin Console";
  if (path.startsWith("/settings")) return "Settings";
  return "RegIntel AI";
}
