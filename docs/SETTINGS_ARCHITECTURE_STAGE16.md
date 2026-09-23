# Settings Architecture - STAGE 16

## 1. Product purpose
A personal settings surface answering what the current user can see and
change about their own experience and session — and stating plainly what
the API does not expose. Small by decision, not by omission.

## 2. Exact settings capabilities discovered
Backend (`app/security/api.py`, verified endpoint by endpoint):

| Capability | Backend | UI |
|---|---|---|
| Identity read (`/security/auth/me`) | Yes | Account card (fresh query) |
| Built-in role reference (`/security/roles`) | Yes | Access-model card, read-only |
| Theme preference | No (browser-local) | Appearance card, LOCAL ONLY |
| Sign-out | Local token cleanup only (Stage 03) | Session card button |
| Profile editing | No | Stated as unavailable |
| Password change | No | Stated as unavailable |
| Server sessions/devices/history | No | Stated as unavailable |
| Notification preferences | No | Stated as unavailable |
| Locale/timezone/language | No | Not built |
| Application defaults | No persisted support | Not built |
| API keys / provider config / density toggle / env-flag display / duplicated health | No or misleading legacy UI | Removed |

## 3. Admin vs Settings boundary
Admin owns: users, roles CRUD, permissions, platform settings, RBAC verdicts,
admin stats. Settings owns: personal identity display, browser-local theme,
local sign-out, access-model reference. Settings links to `/admin` for
account changes and never mirrors admin controls. Platform-setting CRUD
appears nowhere in Settings.

## 4. Identity/profile model
`/me` → `{subject_id, roles[], scopes[], permissions[]}`, rendered verbatim
with "none reported" fallbacks. No profile mutation endpoint exists, so no
editable identity fields exist. This page shares `adminKeys.me()` with the
Admin identity panel — one query, one truth.

## 5. Preferences model
Exactly one: theme preference (`light` | `dark` | `system`), persisted in
`localStorage` under the existing `regintel:theme` key, applied as the
`dark` class + `data-theme` like before. `system` follows the OS media query
with a live listener. Labeled "Local only / Stored on this browser" —
never synced, never implied otherwise.

## 6. Security/session model
Factual panel, no controls invented: access token in tab memory, refresh
token in this browser, no server session list to review or revoke. Sign-out
clears local tokens and routes to login (same semantics as the shell menu);
it is labeled as browser-local because no revoke endpoint exists.

## 7. Notification model
None — no backend. Stated in the Not-available card, not rendered as an
empty table.

## 8. Local vs server-persisted preferences
Only the theme is local; everything else displayed (identity, role grants)
is server-read. There are no server-persisted user preferences to confuse
the two.

## 9. Endpoint inventory
- `GET /security/auth/me` (existing `authApi.getMe`, shared key).
- `GET /security/roles` → `{roles: Record<role, permission[]>,
  permissions: string[]}` (new `securityApi.getRoleGrants`,
  `settingsKeys.roleGrants()`).
- Evaluated and excluded: gateway summary, secrets diagnostics/list
  (infra surfaces, not settings), audit-review endpoints (Audit owns them).

## 10. Query architecture
Two read queries, no parameters, no polling, no mutations on this page.
Theme state stays in the existing provider (no new global framework).

## 11. Mutation/invalidation
None: theme writes go straight to localStorage + DOM (no server round
trip to invalidate); sign-out delegates to the auth provider. Documented
as a decision, not an omission.

## 12. Loading/error/empty states
Per-card Skeletons; ErrorState+Retry with backend messages; empty role
grants states "no built-in roles" only on a successful empty response;
the Not-available card is a capability statement, never an error or an
empty dataset.

## 13. Security handling
No passwords/hashes/tokens/keys rendered, stored, or logged. Removed the
legacy API-key password field (which kept a secret in component state
while claiming browser storage). Theme storage holds only the preference
string. Backend remains the authorization boundary.

## 14. Accessibility
One h1; section structure via card headings; labelled select; real
buttons/links; `aria-live` on the access-model region; `role=alert`
errors; no color-only semantics.

## 15. Responsive behavior
Single narrow column (max-w-3xl); definition grids collapse 3→1;
verified 390/768/1024/1440 with zero overflow
(`landing/_review/ds16-*`, gitignored local artifacts).

## 16. Backend limitations
No profile/password/session/notification/locale/defaults APIs; role-grant
reference is informational (no per-user evaluation — that lives in Admin);
gateway/secrets/audit-review endpoints intentionally unexposed here.

## 17. Deferred features
Everything in §16 awaits backend support; no client-side workarounds are
planned. If a preferences API lands, it gets `settingsKeys.preferences()`
and an explicit save semantic per field — never silent autosave of
sensitive data.
