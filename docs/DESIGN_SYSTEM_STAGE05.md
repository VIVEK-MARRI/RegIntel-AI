# Design System — STAGE 05

One visual language for the authenticated app. Pages keep their structure;
this stage normalizes primitives, tokens, and shared patterns only.
Landing (`landing/`) is frozen and untouched.

## 1. Design principles

Precision, evidence, trust, technical depth, clarity, calm density.
No gradients-as-decoration, no glow clichés, no glassmorphism, no neon.
Inter for UI, JetBrains Mono for technical text. Dense but scannable.

## 2. Theme tokens

Tailwind `darkMode: "class"` (ThemeProvider toggles `documentElement`,
persists `regintel:theme`). Palette lives in `tailwind.config.ts`
(`brand` blue scale, `surface light/dark/-2/-3`, `success/warning/danger/
info`) and is consumed ONLY through semantic classes below — never raw
hex in components. `color-scheme: light dark` is set globally.

### Compact token table

| Token | Light | Dark | Used for |
|---|---|---|---|
| app background | `surface-light-2` #f8fafc | `surface-dark` #0b1120 | `body`, shell main |
| elevated surface | `surface-light` #fff | `surface-dark-2` #111827 | `.card`, topbar, drawers |
| surface | white / `surface-light-3` | `surface-dark-3` / slate-800 | inputs, wells, hover fills |
| border | slate-200/70 | slate-800 | cards, dividers, inputs |
| primary text | slate-900 | slate-100 | titles, values |
| secondary text | slate-700/600 | slate-300/200 | body, controls |
| muted text | slate-500/400 | slate-400/500 | hints, meta, placeholders |
| accent | brand-600/500 | brand-500/400 | primary actions, active nav |
| success / warning / danger / info | emerald / amber / red / sky | same, `-300` text | badges, alerts, toasts |

## 3. Typography

`.page-title` (text-lg semibold) + `.page-description` (sm muted) for
every page header — all 7 header-bearing pages migrated.
`.section-title`, `.body-text`, `.supporting-text` (xs), `.meta-text`
(11px), `.label-text` (Field labels), `font-mono` for IDs/hashes/JSON.
Font stack unchanged (Inter + JetBrains Mono).

## 4. Spacing

Tailwind scale only; card rhythm `p-5` body / `px-5 py-4` header;
section gaps `gap-4`; form stacks `space-y-3/4`. No new scale.

## 5. Radius

`rounded-lg` (controls, rows), `rounded-xl` (menu items, list cards),
`rounded-2xl` (cards, dialogs, bubbles), `rounded-full` (pills, avatars).
`rounded`/`rounded-sm` (old Signup) migrated away.

## 6. Elevation

`shadow-elevated` (cards, toasts, drawers, dialogs), `shadow-glow`
(brand focus moments only: logo mark, hover on select cards). No other
shadows. Borders do most of the separation work.

## 7. Button variants

`Button`: primary / secondary / ghost / danger × sm / md / lg.
States: hover, active (native), `focus-visible` ring (global), disabled
(blocks + dims), loading (spinner + `aria-busy`, children preserved).
Icon-only buttons REQUIRE an accessible name (documented, enforced in
shell/drawers; page audit in Stage 17).

## 8. Form control rules

`Field` (label/hint/error/required) + `Input`/`TextArea`/`Select` share
`.input`. Rules: label always `htmlFor`-linked; error auto-links via
`aria-describedby` + sets `aria-invalid`, announced with `role="alert"`;
hint links when no error; `*` marker is `aria-hidden` with sr-only
"(required)"; `.input[aria-invalid=true]` gets the red treatment;
`:disabled` dims. Do not restyle inputs per page — use `.input`.

## 9. Card/surface rules

- Base surface: `.card` + `CardHeader`/`CardBody` (most content blocks).
- Interactive: `Card interactive` (hover glow, pointer) — rare.
- Not everything is a card: plain sections, wells (`bg-slate-50`), and
  list rows (`rounded-lg/xl` borders) carry dense content without card
  chrome. Avoid nested cards.

## 10. Status/badge rules

`Badge` tones: neutral/success/warning/danger/info/brand (+ optional
dot, `sm`/`md`). Status is NEVER color-only: badges always carry text;
`Metric` deltas include sr-only trend direction; nav active adds
semibold + `aria-current`; progress exposes clamped `aria-valuenow`.

## 11. Alert/error/empty states

`Alert` tones info/success/warning/danger; `danger` uses `role="alert"`,
others `role="status"`; dismissible via labeled × button. `ErrorState`
(title/description from the real error, Retry, optional action,
`role="alert"`). `EmptyState` (title/what-next description/optional
action). Prefer the backend/client message over "Something went wrong";
never render stacks, tokens, or `[object Object]`.

## 12. Loading states

Skeletons for layout stability (decorative: `aria-hidden`, no live-region
spam); spinners for buttons/compact waits (`aria-busy`); `run.isPending`
patterns unchanged. Shimmer/spin collapse under reduced-motion.

## 13. Table rules

`Table` (overflow-x wrapper, optional sr-only `caption`) / `THead` /
`TBody` / `TR` (hover) / `TH` (`scope="col"` by default) / `TD`.
Dense `text-sm`, `px-4 py-3`. No virtualization yet (Stage 17).

## 14. Tabs

Shared `Tabs` (tablist only): roving tabindex, arrows/Home/End,
`aria-selected`, underline + semibold active, stable
`${idPrefix}-tab/panel-*` ids. Pages render the panel:
`role="tabpanel"` + matching ids + `tabIndex={0}`. Migrated:
Compliance, Agents, Audit (identical visuals, full keyboard support).

## 15. Toasts

`ToastProvider` (4.5s default, per-toast override, Esc dismisses latest)
+ `ToastViewport` (bottom-right, `z-50`). Severity = tone; `danger`
asserts (`role="alert"`), others inform. No second feedback system.

## 16. Overlay/dialog rules

Shared `Dialog` (backdrop click, Escape, scroll lock, initial focus,
`aria-modal` + labeling) for FUTURE page stages. Shell drawers keep
their own proven implementation this stage — do not fork a third
pattern; adopt `Dialog` for new dialogs.

## 17. Motion principles

Motion only for navigation state, drawers/menus, loading, and real state
changes (`transition-colors`, drawer `duration-200`, progress `500ms`,
shimmer). Global reduced-motion guard collapses all animation to
near-instant (app CSS only; landing ships separately).

## 18. Responsive principles

Primitives are fluid by default (`w-full`, `min-w-0` truncation,
`overflow-x-auto` tables, `flex-wrap` chips, `max-w-*` dialogs/drawers).
Spot-check widths: 390 / 768 / 1024 / 1440 (see screenshots).

## 19. Accessibility principles

Global visible focus ring; associated labels; error announcement;
scoped headers; status semantics; semantic buttons/links; keyboard tabs,
menus, drawers; decorative hidden. Full audit remains Stage 17.

## 20. Intentionally deferred to Stage 17

Full focus-trap audit, heading-hierarchy pass ( stray `h3`s, pages
without `h1`), table caption rollout, touch targets, contrast audit,
motion audit beyond the global guard, icon system unification.
