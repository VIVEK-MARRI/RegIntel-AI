# Admin Architecture - STAGE 15

## 1. Product purpose
A truthful governance workspace for what the backend actually exposes:
authenticated identity, user accounts, role/permission registry, and typed
platform settings. No user-management theater, no security-score decoration,
no admin-only protection claims the backend does not make.

## 2. Actual administrative capabilities discovered
Backend (`app/api/v1/admin.py`, verified route by route):

| Capability | Endpoints | UI |
|---|---|---|
| Identity | `GET /security/auth/me` | Identity card (fresh query) |
| Users | list (status/role/department/text/page), detail, create (201), partial update, delete (204), grant/revoke role | Users tab, full CRUD |
| Roles | list (built_in/text/page), detail, create (201), full-list permission replace, delete (204; refuses built-in) | Roles tab, full CRUD |
| RBAC check | `GET /rbac/{user}?permission=` verdict | Inside user detail |
| Settings | list, upsert by key, delete (204) | Settings tab, full CRUD |
| Overview/stats | `/overview`, `/stats` aggregates | Compact stats row |
| record_login | `POST /users/{id}/login` | NOT exposed (auth-flow internal) |
| Dashboards | `/governance`, `/audit`, `/compliance` | NOT exposed (owned by dedicated pages) |

## 3. Identity/auth model
`GET /security/auth/me` → `{subject_id, roles[], scopes[], permissions[]}`.
Displayed from a fresh query on this page — never from cached browser data,
and this page is not a second source of truth (no writes to identity).
Missing arrays render as "none reported", never invented defaults. No last
login, MFA, session, or creation data exists here — none is shown.

## 4. Backend authorization model
Verified: authentication is enforced by middleware; **no route in
`admin.py` carries a role or permission dependency**. Every mutation on this
page is callable by any authenticated identity. The `/admin` route guard
(`ROUTE_ROLES`) is a frontend convenience. The page states this openly in
its header note, and no copy claims admin-only protection. 401/403 responses
(when deployments add gates) surface as "Not authorized" distinctly from
transport failures.

## 5. User-management capabilities
Full: server-filtered/paged list, on-demand detail, create (username/email
required; password optional and hashed server-side; roles from the real
registry), partial update (only changed keys sent), grant/revoke by nested
routes (grant idempotent server-side), and delete (204, no server-side
self-delete or usage guard — the UI uses explicit two-click confirmation and
documents this). `password_hash` is returned by the API and is never
rendered, referenced, or logged.

## 6. RBAC/permission capabilities
Real registry: roles bundle `{code, resource, action, description}`
permissions; 7 built-in role names seeded; permission update is FULL-LIST
replacement (the editor warns before save); built-in roles cannot be deleted
(the backend 404s — surfaced verbatim). The per-user verdict panel calls the
real check endpoint (allowed bool + reason + matched roles, `*` wildcard
supported server-side). No frontend permission matrix is invented; role
choices always come from the registry.

## 7. Configuration capabilities
Typed key/value settings with server-inferred `value_type`
(string|int|float|bool|json). The editor coerces by type with client-side
validation (invalid values never reach the network). **Secrets**: `is_secret`
values are never displayed, never pre-filled, editable only by replacement;
secrecy is server-set and not toggleable here (no such field exists).
Deletes confirm twice. No JSON-editor dumps, no env/secret exposure.

## 8. Integration/provider capabilities
NONE exist — no provider, model, key, flag, or maintenance endpoints were
found. No such section exists on the page, by decision (§15).

## 9. Administrative mutations
All in §2 table. Destructive actions (user delete, role delete, setting
delete) require two-click confirmation naming the exact target, disable
while pending, and report backend-verbatim errors. Creates invalidate their
list + stats; updates invalidate list + detail; deletes invalidate list +
stats and close the detail. RBAC checks and permission edits invalidate
nothing global. No optimistic updates on administrative state.

## 10. Query architecture
`adminKeys`: `me()`, `stats()`, `overview()` (reserved), `users(params)` with
every filter + page in the key, `user(id)`, `roles(params)`, `role(id)`,
`rbac(userId, permission)`, `settings()`. Detail/permission data loads on
selection; tab panels mount on activation.

## 11. Cache/invalidation
Narrow and documented in §9. Verified by test: admin traffic stays inside
`/api/v1/admin` + `/security/auth/me` — no cross-domain invalidation exists
because no other domain writes admin state from this UI.

## 12. Loading/error/empty behavior
Independent Skeletons; ErrorState+Retry with backend messages; 401/403 get
their own title; empties distinguish "no matches" from failures and never
imply system emptiness ("No accounts match these filters", never "No users"
as a global claim… except the truly empty store, which the backend reports).

## 13. Security boundaries
Middleware auth is the boundary; no token/secret/hash rendering; secret
settings masked end-to-end; password field is write-only and omitted when
empty; ids path-encoded; free-form input travels as JSON bodies; destructive
actions confirm explicitly. Docs never claim protections the backend lacks.

## 14. Accessibility
One h1 ("Admin Console", kept for the existing page test); Stage-05 Tabs
with keyboard support; labelled inputs/selects/checkboxes; captioned tables
with scoped headers; destructive buttons name their exact target;
`role=alert` errors; `aria-live` lists; `aria-pressed` toggles and
`aria-expanded` disclosure buttons.

## 15. Backend limitations
- No per-route admin gate (see §4).
- No self-delete/usage guards on user deletion.
- `is_secret` immutable from the UI; secret values readable by any
  authenticated caller server-side (UI-side masking only).
- Permission codes are free-form (no backend registry to validate against).
- `record_login` is auth-flow-internal.
- Store durability is deployment-dependent (as with other modules).

## 16. Deferred capabilities
Provider/model/key administration (no backend), feature flags, maintenance
controls, audit-trail views of admin actions (use the Audit page),
bulk user operations, session management, MFA controls.
