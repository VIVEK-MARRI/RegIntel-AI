import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Select } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/providers/AuthProvider";import { useTheme, type ThemePreference } from "@/providers/ThemeProvider";
import { adminKeys, settingsKeys } from "@/lib/queryKeys";
import { getMe } from "@/services/api/authApi";
import { getRoleGrants } from "@/services/api/securityApi";

/**
 * Personal settings workspace: what the current user can actually see and
 * change about their own experience and session.
 *
 * Capability truth (verified against app/security/api.py + providers):
 * - SUPPORTED: read-only identity (/security/auth/me), theme preference
 *   (browser-local), sign-out (local token cleanup), built-in role reference
 *   (GET /security/roles).
 * - LOCAL ONLY: theme choice (stored in this browser, never synced).
 * - UNSUPPORTED: profile editing, password change, server sessions,
 *   notification preferences, locale/timezone, application defaults.
 *   Each is stated as a capability limitation, never as an empty table.
 * - ADMIN-OWNED (linked, never duplicated): users, roles CRUD, permissions,
 *   platform settings.
 */

export function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Settings</h1>
        <p className="page-description">
          Your account, appearance, and session. Platform configuration lives
          in <Link to="/admin" className="text-brand-700 hover:underline dark:text-brand-300">Administration</Link>.
        </p>
      </header>

      <AccountCard />
      <AppearanceCard />
      <SessionCard />
      <AccessModelCard />
      <UnavailableCard />
      <AboutCard />
    </div>
  );
}

function AccountCard() {
  // Shared cache with the Admin identity panel: one /me, one truth.
  const me = useQuery({ queryKey: adminKeys.me(), queryFn: getMe });

  if (me.isPending) {
    return (
      <Card padding="md" aria-label="Account loading">
        <Skeleton className="h-6 w-1/3" />
        <div className="mt-2"><Skeleton lines={2} /></div>
      </Card>
    );
  }
  if (me.isError) {
    return (
      <Card padding="md">
        <ErrorState title="Account unavailable" error={me.error} onRetry={() => void me.refetch()} />
      </Card>
    );
  }
  const d = me.data;
  const roles = arr(d.roles);
  const scopes = arr(d.scopes);
  const perms = arr(d.permissions);
  return (
    <Card padding="none">
      <CardHeader title="Account" description="Read-only identity from the backend" />
      <div className="card-body">
        <p className="text-sm font-semibold text-slate-900 dark:text-white">
          Subject <span className="font-mono">{d.subject_id}</span>
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="meta-text">Roles ({roles.length})</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {roles.length === 0 ? <span className="meta-text">none reported</span> : roles.map((r) => (
                <Badge key={r} size="sm">{r}</Badge>
              ))}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Scopes ({scopes.length})</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {scopes.length === 0 ? <span className="meta-text">none reported</span> : scopes.map((s) => (
                <Badge key={s} size="sm">{s}</Badge>
              ))}
            </dd>
          </div>
          <div>
            <dt className="meta-text">Permissions ({perms.length})</dt>
            <dd className="mt-1 flex flex-wrap gap-1">
              {perms.length === 0 ? <span className="meta-text">none reported</span> : perms.map((p) => (
                <Badge key={p} size="sm">{p}</Badge>
              ))}
            </dd>
          </div>
        </dl>
        <p className="meta-text mt-3">
          Names, emails, and role assignments change in{" "}
          <Link to="/admin" className="text-brand-700 hover:underline dark:text-brand-300">Administration</Link>
          {" "}— this page has no profile editing because the API exposes none.
        </p>
      </div>
    </Card>
  );
}

function arr(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function AppearanceCard() {
  const { preference, setPreference, theme } = useTheme();
  return (
    <Card padding="none">
      <CardHeader
        title="Appearance"
        description="Stored on this browser — never synced to any server"
        actions={<Badge size="sm">Local only</Badge>}
      />
      <div className="card-body">
        <Field label="Theme" id="settings-theme" hint={`Currently applied: ${theme}`}>
          <Select
            id="settings-theme"
            value={preference}
            onChange={(e) => setPreference(e.target.value as ThemePreference)}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="system">System (follow this device)</option>
          </Select>
        </Field>
      </div>
    </Card>
  );
}

function SessionCard() {
  // The auth context is guaranteed in the app shell, but pages must also
  // render in provider-light harnesses: fall back to facts without actions.
  let auth: { logout: () => void } | null = null;
  try {
    auth = useAuth();
  } catch {
    auth = null;
  }
  const navigate = useNavigate();
  return (
    <Card padding="none">
      <CardHeader title="Session" description="How this browser stays signed in" />
      <div className="card-body">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">
          <li>Your access token lives only in this tab's memory.</li>
          <li>A refresh token is kept in this browser to renew it.</li>
          <li>The backend exposes no session list: there is nothing to review or revoke server-side.</li>
        </ul>
        {auth ? (
          <>
            <div className="mt-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  auth.logout();
                  navigate("/login", { replace: true });
                }}
              >
                Sign out of this browser
              </Button>
            </div>
            <p className="meta-text mt-2">
              Signing out clears this browser's tokens. It does not revoke
              anything server-side — no such endpoint exists.
            </p>
          </>
        ) : (
          <p className="meta-text mt-2">
            Sign-out is offered in the account menu when an auth session exists.
          </p>
        )}
      </div>
    </Card>
  );
}

function AccessModelCard() {
  const grants = useQuery({ queryKey: settingsKeys.roleGrants(), queryFn: getRoleGrants });
  return (
    <Card padding="none">
      <CardHeader title="Access model" description="Built-in roles and their permission grants (read-only reference)" />
      <div className="card-body" aria-live="polite">
        {grants.isPending ? (
          <Skeleton lines={4} />
        ) : grants.isError ? (
          <ErrorState title="Access model unavailable" error={grants.error} onRetry={() => void grants.refetch()} />
        ) : Object.keys(grants.data.roles ?? {}).length === 0 ? (
          <EmptyState title="No role data" description="The backend reported no built-in roles." />
        ) : (
          <dl className="space-y-3">
            {Object.entries(grants.data.roles).map(([role, perms]) => (
              <div key={role}>
                <dt className="text-sm font-semibold text-slate-900 dark:text-slate-100">{role}</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {perms.length === 0 ? (
                    <span className="meta-text">no permissions listed</span>
                  ) : (
                    perms.map((p) => (
                      <Badge key={p} size="sm">{p}</Badge>
                    ))
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </Card>
  );
}

function UnavailableCard() {
  return (
    <Card padding="none">
      <CardHeader title="Not available" description="Capabilities the current API does not expose" />
      <div className="card-body">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">
          <li>Profile editing (name, email, department).</li>
          <li>Password changes.</li>
          <li>Server-side sessions, device lists, or login history.</li>
          <li>Notification preferences.</li>
          <li>Language, timezone, or locale settings.</li>
          <li>Application defaults (these pages keep their own last-used values where shown).</li>
        </ul>
        <p className="meta-text mt-2">
          Each item above is a missing backend capability, not an empty
          dataset. User and platform administration lives in{" "}
          <Link to="/admin" className="text-brand-700 hover:underline dark:text-brand-300">Administration</Link>.
        </p>
      </div>
    </Card>
  );
}

function AboutCard() {
  return (
    <Card padding="none">
      <CardHeader title="About" />
      <div className="card-body text-sm text-slate-600 dark:text-slate-300">
        <p>RegIntel AI — Regulatory Intelligence Platform.</p>
      </div>
    </Card>
  );
}
