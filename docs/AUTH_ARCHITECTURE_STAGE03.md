# Auth Architecture — STAGE 03

Authoritative session/auth layer for the RegIntel SPA. Built on the
Stage 02 foundation (`lib/api.ts` single-flight 401→refresh→retry,
canonical `ApiClientError`, correct auth DTOs). No global store:
**AuthProvider owns session state.**

## 1. Authentication components

| Piece | File | Owns |
|---|---|---|
| `AuthProvider` / `useAuth` | `frontend/src/providers/AuthProvider.tsx` | lifecycle, identity, bootstrap, login/logout, refresh scheduling, roles, demo gate |
| HTTP client + `setAuthHandler` | `frontend/src/lib/api.ts` | requests, 401 detection, single-flight refresh orchestration, retry-once |
| Token memory | `frontend/src/lib/auth-token.ts` | in-memory access token only |
| Service calls | `frontend/src/services/api/authApi.ts` | `login` / `signup` / `refreshToken` / `getMe` (typed per backend) |
| Guards | `components/auth/ProtectedRoute.tsx`, `RequireRole.tsx` | bootstrap wait, login redirect, role gates |
| Pages | `pages/LoginPage.tsx`, `pages/SignupPage.tsx` | forms only; zero token logic |

## 2. Login lifecycle

1. `LoginPage` trims + lowercases email, blocks double submit, calls
   `login(email, password)`.
2. `AuthProvider.login`: bumps generation (invalidates stale async work),
   `POST /security/auth/login` → `LoginResponse` (WITH user).
3. Roles normalized once (`normalizeRoles(roles ∪ rbac_roles)`, unknown
   dropped). Query cache cleared (previous identity's data can never leak).
4. Tokens persisted (access→memory, refresh→localStorage), timer scheduled,
   status → `authenticated`.
5. Page navigates to `getSafeRedirect(from)` (same-origin path only).

## 3. Token lifecycle

- **Access token**: memory only (`lib/auth-token`), attached as
  `Bearer` by the HTTP client. Lost on reload by design.
- **Refresh token**: `localStorage regintel_refresh_token`. Readable by any
  JS — see §12. No HttpOnly-cookie option exists backend-side.
- **Cached user**: `localStorage regintel_user`, defensively parsed.
  Treated as CACHE: bootstrap replaces its roles with fresh `/me` roles.

## 4. Session bootstrap

1. Status `unknown`; protected routes spin, never render authed content.
2. Demo requested? → dev: synthetic session; prod: REFUSE (fail closed).
3. Else: stored refresh? → shared in-flight `runBootstrap()` (StrictMode
   double-mount safe): `refresh` → store access in memory → `/me` →
   merged user. Any failure → `{ok:false}` → wipe + `unauthenticated`.
4. No stored token → `unauthenticated`, no network.

## 5. Refresh lifecycle (two mechanisms, one implementation)

- **Proactive**: one timer per session, fires at `max(10s, expires-30s)`;
  rescheduled after every success; cleared on logout/unmount.
- **Reactive**: 401 → Stage 02 client single-flights `rotate()`; one retry.
- `rotate()` is itself single-flight (timer + sleep-resume + 401 share it).
- Sleep/resume: on `visibilitychange visible`, rotate when the access
  token is past/near expiry.
- Auth endpoints (`login`/`refresh`/`signup`) never trigger refresh.

## 6. 401 recovery

ONE rotation, MANY waiters, ONE retry each; refresh failure → queued
requests reject, session terminates, login shows "session expired".
A 401 surviving retry throws without looping and keeps the fresh session.
Concurrent 401s share one refresh (tested). Logout bumps generation so
late completions can never restore the old session.

## 7. getMe / revalidation

`GET /security/auth/me` → `{subject_id, roles, scopes, permissions}`.
Called once per bootstrap and per rotation; roles from `/me` REPLACE
cached roles. Never per-render. Failures: bootstrap fails closed;
background rotation keeps fresh tokens with cached identity.

## 8. Logout behavior

Backend has NO logout/revoke endpoint (verified: no route in
`app/security/api.py`; refresh JTIs rotate server-side). Logout is
local-only and honest about it:
generation++ → timers cleared → tokens/user/storage wiped → status
`unauthenticated` → `cancelQueries` + `clear()` (next identity starts
clean) → caller navigates to `/login`. Demo mode: no-op (nothing real).
A stolen refresh token remains valid server-side until expiry/rotation.

## 9. RBAC model

Backend `Role`: viewer, analyst, operator, auditor, admin, service
(`app/security/rbac.py`); backend permissions are the real boundary and
NO frontend route is server-gated by role today. Client guards are
UI-only: `normalizeRoles()` in one place, unknown roles dropped,
`hasRole()` requires an authenticated server-validated session, stale
persisted roles are replaced on every bootstrap. No `admin = everything`
logic exists client-side.

## 10. Demo-mode behavior

Opt-in ONLY via literal `VITE_AUTH_ENABLED=false`. Dev builds install an
explicit synthetic all-roles session (`demoMode: true`, console warning).
**Production builds refuse it** (`resolveDemoAccess` → deny): status
`unauthenticated` + error, real sign-in required. A missing variable
means auth ON (safe default). No secrets in Vite env (all client-visible).

## 11. Session / query-cache cleanup

`logout()` and `login()` both `cancelQueries` + `clear()` the shared
`QueryClient` (all factories in `lib/queryKeys.ts`). User B can never see
User A's conversations/documents/audit/analytics. No ad-hoc caches.

## 12. Security limitations (honest)

1. Refresh token in readable localStorage: XSS-stealable until expiry.
   Mitigation ownership is backend (cookies/revocation endpoint) — absent.
2. No server-side logout: stolen tokens survive local logout.
3. Client role guards are UX, not security; backend RBAC is authoritative.
4. `Bearer demo` is sent in demo/dev builds; backend demo principal is
   full-access when its own `AUTH_ENABLED=false`.
5. Persisted sessions are validated on every bootstrap (refresh + /me),
   so tampered roles grant nothing without a live backend session.

## 13. Known backend limitations

- No `POST /security/auth/logout` or revocation API.
- Refresh returns `TokenResponse` WITHOUT user (frontend types this
  correctly; identity comes from `/me`).
- No role-gated routes server-side today (`require_role` unused).
- Demo principal (`AUTH_ENABLED=false`) is full-access.

## 14. Sequence diagram

```
User
 |
 | login(email, password)
 v
LoginPage (trim, validate, disable dup submit)
 |
 v
AuthProvider.login
 |
 v
authApi  -->  POST /security/auth/login  -->  FastAPI auth endpoint
 |
 v
LoginResponse (tokens + user)
 |
 +---- access token -> memory (lib/auth-token)
 +---- refresh token -> localStorage
 +---- roles -> normalizeRoles()
 +---- query cache cleared
 |
 v
AUTHENTICATED (+ proactive refresh timer)
 |
 v
Protected APIs (Bearer attached by HTTP client)
 |
 | 401
 v
Stage 02 API client (single-flight)
 |
 v
AuthProvider.rotate -> POST /security/auth/refresh -> GET /security/auth/me
 |
 +---- success: fresh tokens, retry original once
 +---- failure: clear session, login shows "session expired"
 v
Logout (local only: clear tokens/timers/cache -> /login)
```
