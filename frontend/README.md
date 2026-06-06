# RegIntel AI — Frontend (M10.1 + M10.2)

Professional user experience platform for the RegIntel AI multi-agent regulatory
intelligence system. Provides a complete enterprise UI on top of the existing
backend APIs.

## Stack

- **React 18** with **TypeScript 5** in **strict** mode
- **Vite 5** for tooling and dev server
- **TailwindCSS 3** with a custom design system
- **TanStack Query 5** for server-state management
- **React Router 6** for client-side routing
- **Recharts 2** for analytics visualisations
- **Vitest + Testing Library** for component, integration, and accessibility tests
- **jsdom** for browser-like test environment

## Features

### M10.1 — Frontend Platform

- 14 enterprise pages: Dashboard, Copilot, Research, Compliance, Risk, Knowledge
  Graph, Agent Control Center, Agent Collaboration, Agent Health, Agent
  Workflows, Governance, Audit, Admin, Settings, plus a 404 page
- Responsive design with **dark mode** (class-based, persisted in localStorage)
- Reusable design system: `Button`, `Card`, `Badge`, `Skeleton`, `EmptyState`,
  `ErrorState`, `Alert`, `ProgressBar`, `Table`, `Field/Input/Select/TextArea`,
  `Metric`, `Toast` viewport
- **Copilot Chat** with full conversation lifecycle: streaming-ready, citation
  viewer, source attribution viewer, confidence and faithfulness indicators,
  hallucination risk badge, conversation history, short/long-term memory context
  display, and per-agent contribution cards
- Suggested prompts, multi-pane layout (sessions + chat + context)
- Toast notification system with auto-dismiss and `aria-live` region
- Accessibility: ARIA landmarks, focus rings, semantic roles, keyboard handling

### M10.2 — Agent Control Center

- **Agent fleet view** with per-agent health, success rate, latency, and
  confidence metrics
- **Quick execute** panel — pick an agent, run with a prompt, view JSON result
- **Per-agent detail** with capabilities, latency percentiles (p50/p90/p95/p99)
- **Leaderboard** with composite score (`0.6·success + 0.3·confidence + 0.1·speed`)
- **Agent health dashboard** (per-agent health, latency distribution, error tail)
- **Agent collaboration** page (multi-agent collaboration records + live message
  bus with 5 s polling)
- **Agent workflows** page (create + run multi-step agent plans)
- **Real-time telemetry** (15–30 s refetch intervals)

## Project structure

```
frontend/
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── vitest.config.ts
└── src/
    ├── App.tsx
    ├── main.tsx
    ├── index.css                 # Tailwind + design system
    ├── components/
    │   ├── layout/AppShell.tsx   # Sidebar + Topbar
    │   └── ui/                   # Reusable primitives
    ├── hooks/api.ts              # TanStack Query bindings to backend
    ├── lib/
    │   ├── api.ts                # fetch wrapper + ApiClientError
    │   └── format.ts             # Display helpers
    ├── pages/                    # One file per route
    ├── providers/
    │   ├── ThemeProvider.tsx
    │   └── ToastProvider.tsx
    ├── test/                     # Component + integration + a11y tests
    └── types/index.ts            # Shared TypeScript contracts
```

## Backend contract

All HTTP calls go through `/api/v1/*`. In development the Vite dev server
proxies `/api` to `http://localhost:8000`, so no environment configuration is
required. The API base can be overridden at runtime via Settings.

Pages consume the existing M5–M9 endpoints — no backend services are rebuilt or
re-implemented by the frontend. See `hooks/api.ts` for the full query surface.

## Scripts

| Command            | Description                                    |
| ------------------ | ---------------------------------------------- |
| `npm run dev`      | Vite dev server on http://localhost:5173       |
| `npm run build`    | Type-check and produce `dist/`                 |
| `npm run preview`  | Preview the production build                   |
| `npm test`         | Run the Vitest suite once                      |
| `npm run test:watch` | Vitest in watch mode                         |
| `npm run typecheck` | `tsc --noEmit`                               |
| `npm run lint`     | ESLint over `src/`                             |

## Testing strategy

| Layer              | Coverage                                                  |
| ------------------ | --------------------------------------------------------- |
| Component          | UI primitives + key flows (`ui.test.tsx`)                 |
| Pages (smoke)      | All 15 pages render their primary heading (`pages.test.tsx`) |
| Integration        | Providers + routing + viewport (`integration.test.tsx`)   |
| API hooks          | Mocked fetch + query state (`api.test.tsx`)               |
| Accessibility      | Landmarks + link semantics (`accessibility.test.tsx`)     |
| Provider           | Theme + Toast behaviour + persistence                     |
| Utilities          | `format.ts` (pure functions)                              |

Total: **44 tests, 8 files, 0 flakes**.

## Design system

| Token        | Value                                  |
| ------------ | -------------------------------------- |
| Brand        | `brand-50` … `brand-950` (blue palette) |
| Surface      | `surface-light/2/3` + `surface-dark/2/3` |
| Semantic     | `success`, `warning`, `danger`, `info` |
| Typography   | Inter (UI), JetBrains Mono (code)      |
| Radii        | `xl` (0.875 rem), `2xl` (1.125 rem)     |
| Shadows      | `elevated`, `glow`                     |
| Motion       | `pulse-soft`, `shimmer` (skeleton)     |

Dark mode is opt-in (system preference by default) and persists to
`localStorage` under `regintel:theme`.

## Versioning

`10.0.0` — Initial User Experience Platform release (M10.1 + M10.2).
