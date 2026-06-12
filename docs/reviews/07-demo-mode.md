# Demo Mode Review

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AUTH_ENABLED` (backend) | `true` | Set to `false` to bypass all auth checks |
| `VITE_AUTH_ENABLED` (frontend) | `"true"` | Set to `"false"` to skip auth on the frontend |

## How It Works (Backend)

When `REGINTEL_AUTH_ENABLED=false`:

1. **`_principal_from_request()`** returns a full-admin `Principal` (all roles) for every request, regardless of the `Authorization` header
2. **`POST /auth/login`** returns a demo JWT pair without validating credentials
3. **`POST /auth/signup`** returns a demo JWT pair without creating a user
4. **`POST /auth/refresh`** returns a fresh demo JWT pair even without a refresh token
5. **`GET /health/live`, `/health/ready`, `/health/deep`** — all work normally (no auth guard)
6. **CORS** — set to allow all origins (`*`) for easy cross-origin demo access

## How It Works (Frontend)

When `VITE_AUTH_ENABLED=false`:

1. **`AuthProvider`** sets a demo admin user immediately on mount (no network calls)
2. **`isAuthenticated`** is always `true`
3. **`login()`** sets the demo user without making API calls
4. **`logout()`** is a no-op
5. **`hasRole()`** always returns `true`
6. **`ProtectedRoute`** and **`RequireRole`** let all requests through
7. **`LoginPage`** and **`SignupPage`** auto-redirect to `/` since `isAuthenticated=true`
8. **`AppShell`** hides the "Sign out" button and shows a "Demo" badge in the top bar

## Production Safeguards

- `Omit on default` — `AUTH_ENABLED` defaults to `true`, so demo mode is opt-in via explicit configuration
- Frontend must be built with `VITE_AUTH_ENABLED=false` — not configurable at runtime
- The demo principal has **all roles** (`admin`, `analyst`, `operator`, `auditor`) — no role-based restrictions
- No persistent state (no users created, no tokens stored in localStorage)
