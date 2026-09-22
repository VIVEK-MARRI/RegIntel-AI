import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { useTheme } from "@/providers/ThemeProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useHealth } from "@/providers/HealthProvider";
import { useIsDesktop } from "@/lib/useMediaQuery";
import { ToastViewport } from "@/components/ui/ToastViewport";
import {
  ADMIN_NAV_ITEMS,
  NAV_ITEMS,
  titleForPath,
  visibleNavItems,
  type NavItem,
} from "@/components/layout/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

const COLLAPSE_KEY = "regintel:sidebar-collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function Sidebar({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const { theme, toggle } = useTheme();
  const { hasRole } = useAuth();

  const items = visibleNavItems(NAV_ITEMS, hasRole);
  const extraItems = visibleNavItems(ADMIN_NAV_ITEMS, hasRole);

  const renderItem = (item: NavItem) => (
    <li key={item.to}>
      <NavLink
        to={item.to}
        end={item.end}
        onClick={onNavigate}
        className={({ isActive }) =>
          clsx("nav-link", isActive && "nav-link-active")
        }
        title={collapsed ? item.label : undefined}
        aria-label={collapsed ? item.label : undefined}
      >
        <NavIcon name={item.icon} />
        {!collapsed ? <span className="truncate">{item.label}</span> : null}
      </NavLink>
    </li>
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
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow"
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

      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Sections">
        <ul className="space-y-0.5">{items.map(renderItem)}</ul>
        {extraItems.length > 0 && (
          <>
            <hr className="my-3 border-slate-200 dark:border-slate-700" />
            <ul className="space-y-0.5" aria-label="Administration">
              {extraItems.map(renderItem)}
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

function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      document.getElementById("shell-menu-button")?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        data-testid="nav-backdrop"
        className="absolute inset-0 h-full w-full cursor-default bg-slate-950/50"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Primary navigation"
        className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-elevated dark:bg-surface-dark-2"
      >
        <div className="flex items-center justify-end border-b border-slate-200 p-2 dark:border-slate-800">
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <Sidebar collapsed={false} onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}

export function Topbar({
  onMenuToggle,
  menuButtonLabel,
}: {
  onMenuToggle: () => void;
  menuButtonLabel: string;
}) {
  const location = useLocation();
  const title = titleForPath(location.pathname);
  return (
    <header
      className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur
                 dark:border-slate-800 dark:bg-surface-dark-2/80"
    >
      <button
        id="shell-menu-button"
        type="button"
        onClick={onMenuToggle}
        aria-label={menuButtonLabel}
        className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <p className="min-w-0 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
        {title}
      </p>
      <div className="flex-1" />
      <SystemStatusPill />
      <AccountMenu />
    </header>
  );
}

function SystemStatusPill() {
  const { isLoading, isError, isHealthy, isDegraded } = useHealth();
  const state = isLoading
    ? { label: "Checking…", dot: "bg-slate-400", ring: "border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-800/40 dark:text-slate-400" }
    : isError || (!isHealthy && !isDegraded)
      ? { label: "Unavailable", dot: "bg-red-500", ring: "border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300" }
      : isDegraded
        ? { label: "Degraded", dot: "bg-amber-500", ring: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300" }
        : { label: "Operational", dot: "bg-emerald-500", ring: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300" };
  return (
    <div
      className={clsx(
        "hidden items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium sm:flex",
        state.ring
      )}
      role="status"
    >
      <span aria-hidden className={clsx("h-1.5 w-1.5 rounded-full", state.dot)} />
      <span>{state.label}</span>
    </div>
  );
}

function AccountMenu() {
  const [open, setOpen] = useState(false);
  const { user, logout, demoMode } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open ]);

  const initials = user?.full_name
    ? user.full_name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : user?.username?.slice(0, 2).toUpperCase() || "?";

  const displayName = user?.full_name || user?.username || "User";
  const email = user?.email || "";

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
        className="flex max-w-[11rem] items-center gap-2 rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-50
                   dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-200 dark:hover:bg-slate-800"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${displayName}`}
      >
        <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500 text-[10px] font-semibold text-white">
          {initials}
        </span>
        <span className="hidden truncate sm:inline">{displayName}</span>
      </button>
      {open ? (
        <>
          <button
            type="button"
            aria-label="Close account menu"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-10 cursor-default bg-transparent"
          />
          <div
            role="menu"
            aria-label="Account"
            className="absolute right-0 top-9 z-20 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 text-xs shadow-elevated
                       dark:border-slate-700 dark:bg-surface-dark-2"
          >
            <div className="border-b border-slate-200 px-3 py-2 dark:border-slate-700">
              <p className="truncate font-semibold text-slate-900 dark:text-slate-100">{displayName}</p>
              {email ? <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{email}</p> : null}
              {demoMode ? (
                <p className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                  Demo session
                </p>
              ) : null}
            </div>
            {!demoMode ? (
              <button
                type="button"
                role="menuitem"
                className="block w-full px-3 py-2 text-left text-red-600 transition hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
                onClick={handleSignOut}
              >
                Sign out
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

export function ShellBootSplash() {
  return (
    <div className="flex h-full w-full items-center justify-center" role="status" aria-label="Loading application">
      <div className="text-center">
        <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
        <p className="text-xs text-slate-500 dark:text-slate-400">Loading workspace…</p>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  const isDesktop = useIsDesktop();
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (isDesktop) setDrawerOpen(false);
  }, [isDesktop]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* persistence is best-effort */
      }
      return next;
    });
  };

  if (status === "unknown") {
    return (
      <div className="flex h-full w-full overflow-hidden">
        <ShellBootSplash />
      </div>
    );
  }

  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className="hidden lg:flex lg:shrink-0">
        <Sidebar collapsed={collapsed} />
      </div>
      <MobileDrawer open={drawerOpen && !isDesktop} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          onMenuToggle={() => {
            if (isDesktop) toggleCollapsed();
            else setDrawerOpen(true);
          }}
          menuButtonLabel={
            isDesktop
              ? collapsed
                ? "Expand sidebar"
                : "Collapse sidebar"
              : "Open navigation"
          }
        />
        <main className="flex-1 overflow-y-auto bg-surface-light-2 p-4 sm:p-6 dark:bg-surface-dark">
          {children}
        </main>
      </div>
      <ToastViewport />
    </div>
  );
}
