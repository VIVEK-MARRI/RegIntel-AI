# Shell Architecture — STAGE 04

Authenticated app chrome only. Pages, landing, design system untouched.

## 1. Shell hierarchy

```mermaid
App
 |
 +-- ProtectedLayout (App.tsx: thin route table)
 |     |
 |     +-- Shell (components/layout/AppShell.tsx: owns chrome state)
 |     |     |
 |     |     +-- Sidebar / MobileDrawer (desktop / <lg)
 |     |     |
 |     |     +-- Topbar
 |     |           +-- SystemStatus (live HealthProvider)
 |     |           +-- AccountMenu (identity + Sign out only)
 |     |
 |     +-- MainContent (page Routes)
 |     |
 |     +-- ToastViewport
```

`Shell` owns: `collapsed` (persisted `regintel:sidebar-collapsed`),
`drawerOpen`, bootstrap gate. Nothing else owns chrome state (no store).

## 2. Route map

`/login`, `/signup` public (outside shell). Inside shell, all guarded:
`/` Dashboard; `/copilot` + `/copilot/:conversationId`; `/research` +
`/research/:reportId`; `/documents`; `/knowledge-graph`; `/compliance`;
`/audit`; `/analytics`; `/settings`; `/agents` (admin/operator/analyst);
`/admin` (admin); `*` guarded → login for anonymous, NotFound for authed.
Nested routes activate their section (`NavLink` prefix match; `/` exact).

## 3. Navigation configuration

`components/layout/navigation.ts` is the single source: `NAV_ITEMS` (9),
`ADMIN_NAV_ITEMS` (Agents, Admin), `ROUTE_ROLES` (consumed by App.tsx
guards — links and guards cannot disagree), `titleForPath`,
`visibleNavItems()`. Icons stay co-located in AppShell.

## 4. Role visibility matrix

| Role | Base 9 | AI Agents | Admin |
|---|---|---|---|
| viewer / analyst / auditor | ✓ | — | — |
| operator | ✓ | ✓ | — |
| admin | ✓ | ✓ | ✓ |
| service / unknown | ✓ base only (fail safe) | — | — |

UX-only (NOT security): backend authorization remains authoritative.
Analyst seeing Agents is intentional parity with the route guard.

## 5. Desktop behavior

Fixed sidebar (`w-64`, icon-only `w-16` when collapsed via Topbar button;
labels persist in `title` + `aria-label`). Collapse persists per browser.
Active link: background + semibold + `aria-current="page"` (never
color-only). Content `min-w-0` prevents sidebar squeeze.

## 6. Tablet behavior (768–1023)

Drawer navigation (same component as mobile): hamburger opens, sidebar
hidden. Content full-width. Verified 768×1024: no overflow.

## 7. Mobile behavior (390px)

No fixed sidebar. Hamburger (`Open navigation`) → `role=dialog`
`aria-modal` drawer (`w-72`, max 85vw): backdrop click closes, Escape
closes, link selection closes (route change), body scroll locked,
focus to close button on open and back to the hamburger on close.
Verified 390×844: drawer opens, 0px horizontal overflow, zero errors.

## 8. Sidebar state

`collapsed: boolean` (desktop only; localStorage, best-effort).
`drawerOpen: boolean` (mobile/tablet; auto-closes on navigation and on
crossing to desktop). No viewport resize listeners — one `matchMedia`
subscription (`lib/useMediaQuery.ts`).

## 9. Mobile drawer behavior

See §7. Backdrop is click-only (`aria-hidden`, keyboard users get Escape
+ close button). Focus trap is intentionally minimal (close on Escape,
focus restoration); full trap deferred to Stage 17.

## 10. Topbar behavior

Hamburger is contextual: collapses sidebar on desktop, opens the drawer
below `lg` (dynamic `aria-label`). Title truncates; status pill hides on
`xs`; account menu never overflows (max-width + truncation).

## 11. Account menu

Identity header (name/email, `Demo session` badge when applicable) +
**Sign out only**. Profile / API Keys / Activity Log removed — no
destinations exist and dead controls are banned. Escape + outside-click
close. Sign out delegates to `useAuth().logout()` then `/login`.

## 12. Health/status integration

`SystemStatusPill` reads `useHealth()` (owned/poll by HealthProvider,
30s): Checking… / Operational / Degraded / Unavailable — text + color,
never hardcoded, no toasts.

## 13. Copilot mobile navigation

Same `SessionList` (same data/callbacks, zero state duplication) rendered
in a mobile drawer behind a `lg:hidden` Conversations trigger; selecting
or creating a chat closes it and navigates. Desktop column unchanged.

## 14. Accessibility decisions

NavLink `aria-current`; collapsed links keep `aria-label`; dialog semantics
on drawers; Escape everywhere; backdrop click-only; focus in/out of
drawers; menu `aria-expanded` + `role=menu/menuitem`; active state
semibold; skip-link/full trap left for Stage 17.

## 15. Known limitations

- Unauthenticated shell flashes at most one frame before the guard
  redirect (inner `Protect` owns the redirect with return target).
- Drawer uses a minimal focus scope, not a full trap (Stage 17).
- `service` role gets base nav (no evidence for a distinct shell).
- Long sessions rely on Stage 03 refresh; shell adds no polling.
- Viewport screenshots: `landing/_review/shell-*.png` (gitignored).
