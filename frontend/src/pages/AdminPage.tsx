import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Field, Input, Select } from "@/components/ui/Field";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative } from "@/lib/format";
import { ApiClientError } from "@/lib/errors";
import { adminKeys } from "@/lib/queryKeys";
import { getMe } from "@/services/api/authApi";
import {
  checkRBAC,
  createRole,
  createUser,
  deleteRole,
  deleteSetting,
  deleteUser,
  getAdminStats,
  getRole,
  getRoles,
  getSettings,
  getUser,
  getUsers,
  grantRole,
  revokeRole,
  setSetting,
  updateRolePermissions,
  updateUser,
} from "@/services/api/adminApi";
import type {
  AdminPermission,
  AdminRole,
  AdminUser,
  AdminUserStatus,
  PlatformSetting,
} from "@/types/api/admin";

/**
 * Administration workspace: identity, users, roles, and platform settings —
 * exactly what the backend exposes, nothing conventional-but-absent.
 *
 * Authorization truth (verified in app/api/v1/admin.py + middleware):
 * - The API requires authentication (middleware), but defines NO admin-only
 *   role/permission gate on any admin route. The /admin route guard is a
 *   frontend convenience, not a security boundary. This page states that
 *   openly instead of implying admin-only protection.
 * - User password hashes are returned by the API and are NEVER rendered.
 * - Secret settings show "hidden" and are never displayed or edited in place.
 */

type TabId = "users" | "roles" | "settings";

const TABS = [
  { id: "users" as const, label: "Users" },
  { id: "roles" as const, label: "Roles" },
  { id: "settings" as const, label: "Settings" },
];

const USER_PAGE_SIZE = 50;
const ROLE_PAGE_SIZE = 50;
const VALUE_TYPES = ["string", "int", "float", "bool", "json"];

function isAuthError(err: unknown): boolean {
  return err instanceof ApiClientError && (err.status === 401 || err.status === 403);
}
function errTitle(fallback: string, err: unknown): string {
  return isAuthError(err) ? "Not authorized (401/403)" : fallback;
}

/** Runtime guards: backend shapes are trusted but never assumed. */
function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

/** Coerce a text input to a setting value by its declared value_type. */
function coerceSettingValue(
  text: string,
  valueType: string
): { value: unknown; error: string | null } {
  const t = text.trim();
  switch (valueType) {
    case "int": {
      if (!/^-?\d+$/.test(t)) return { value: null, error: "Expected an integer." };
      return { value: Number.parseInt(t, 10), error: null };
    }
    case "float": {
      const n = Number(t);
      if (t === "" || !Number.isFinite(n)) return { value: null, error: "Expected a number." };
      return { value: n, error: null };
    }
    case "bool": {
      if (t !== "true" && t !== "false") return { value: null, error: 'Expected "true" or "false".' };
      return { value: t === "true", error: null };
    }
    case "json": {
      try {
        return { value: JSON.parse(t), error: null };
      } catch {
        return { value: null, error: "Value is not valid JSON." };
      }
    }
    default:
      return { value: text, error: null };
  }
}
function settingToText(value: unknown, valueType: string): string {
  if (value === null || value === undefined) return "";
  if (valueType === "json" && typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return "";
    }
  }
  return String(value);
}

export function AdminPage() {
  const [tab, setTab] = useState<TabId>("users");

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Admin Console</h1>
        <p className="page-description">
          Identity, users, roles, and platform settings as exposed by the API.
        </p>
        <p className="meta-text mt-1">
          Access note: this route is gated in the UI only. The API requires
          authentication, but every endpoint on this page is callable by any
          authenticated identity — no role gate exists server-side.
        </p>
      </header>

      <IdentityCard />
      <StatsRow />

      <Tabs
        items={TABS}
        value={tab}
        onChange={(id) => setTab(id as TabId)}
        label="Administration sections"
        idPrefix="admin"
      />

      <div role="tabpanel" id={`admin-panel-${tab}`} aria-labelledby={`admin-tab-${tab}`} tabIndex={0}>
        {tab === "users" && <UsersTab />}
        {tab === "roles" && <RolesTab />}
        {tab === "settings" && <SettingsTab />}
      </div>
    </div>
  );
}

/* ─── identity (authoritative /me, not localStorage) ───────────────── */

function IdentityCard() {
  const me = useQuery({ queryKey: adminKeys.me(), queryFn: getMe });

  if (me.isPending) {
    return (
      <Card padding="md" aria-label="Identity loading">
        <Skeleton className="h-6 w-1/3" />
        <div className="mt-2"><Skeleton lines={2} /></div>
      </Card>
    );
  }
  if (me.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title={errTitle("Identity unavailable", me.error)}
          error={me.error}
          onRetry={() => void me.refetch()}
        />
      </Card>
    );
  }
  const d = me.data;
  const roles = arr(d.roles).filter((r): r is string => typeof r === "string");
  const scopes = arr(d.scopes).filter((r): r is string => typeof r === "string");
  const perms = arr(d.permissions).filter((r): r is string => typeof r === "string");
  return (
    <Card padding="md">
      <h2 className="text-sm font-semibold text-slate-900 dark:text-white">
        Signed in as <span className="font-mono">{d.subject_id}</span>
      </h2>
      <p className="meta-text mt-0.5">Identity and grants below come from a fresh backend check, not cached browser data.</p>
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
    </Card>
  );
}

function StatsRow() {
  const stats = useQuery({ queryKey: adminKeys.stats(), queryFn: getAdminStats });
  if (stats.isPending) {
    return (
      <section aria-label="Administration overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </section>
    );
  }
  if (stats.isError) {
    return (
      <ErrorState title={errTitle("Statistics unavailable", stats.error)} error={stats.error} onRetry={() => void stats.refetch()} />
    );
  }
  const s = stats.data;
  return (
    <section aria-label="Administration overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Metric label="Users" value={s.total_users.toLocaleString()} hint={`${s.active_users} active · ${s.suspended_users} suspended`} />
      <Metric label="Roles" value={s.total_roles.toLocaleString()} hint={`${s.built_in_roles} built-in`} />
      <Metric label="Permissions" value={s.total_permissions.toLocaleString()} hint="Across all roles" />
      <Metric label="Settings" value={s.total_settings.toLocaleString()} hint={`${s.secret_settings} marked secret (values hidden)`} />
    </section>
  );
}

/* ─── users ────────────────────────────────────────────────────────── */

function UsersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [textQuery, setTextQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const listQuery = useMemo(
    () => ({
      status: (status || undefined) as AdminUserStatus | undefined,
      department: department.trim() || undefined,
      text_query: textQuery.trim() || undefined,
      page: page + 1,
      page_size: USER_PAGE_SIZE,
    }),
    [status, department, textQuery, page]
  );
  const users = useQuery({
    queryKey: adminKeys.users(listQuery),
    queryFn: () => getUsers(listQuery),
  });
  // Role names for display + assignment come from the real role registry.
  const allRoles = useQuery({
    queryKey: adminKeys.roles({ page_size: 200 }),
    queryFn: () => getRoles({ page_size: 200 }),
  });
  const roleName = (id: string) =>
    (allRoles.data?.items ?? []).find((r) => r.role_id === id)?.name ?? id;

  const create = useMutation({
    mutationFn: createUser,
    onSuccess: (u) => {
      void qc.invalidateQueries({ queryKey: [...adminKeys.all, "users"] });
      void qc.invalidateQueries({ queryKey: adminKeys.stats() });
      setShowCreate(false);
      setSelectedId(u.user_id);
      toast.push({ title: "User created", description: u.username, tone: "success" });
    },
  });

  const list = users.data?.items ?? [];
  const shortPage = list.length < USER_PAGE_SIZE;

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Users"
          description="Platform accounts with server-side filters"
          actions={
            <Button variant="secondary" size="sm" onClick={() => setShowCreate((v) => !v)} aria-expanded={showCreate}>
              {showCreate ? "Close form" : "New user"}
            </Button>
          }
        />
        <div className="card-body" aria-live="polite">
          <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Select aria-label="Filter users by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} className="text-xs">
              <option value="">All statuses</option>
              {["active", "invited", "suspended", "disabled"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
            <Input aria-label="Search users" value={textQuery} onChange={(e) => { setTextQuery(e.target.value); setPage(0); }} placeholder="Username or email…" className="text-xs" />
            <Input aria-label="Filter users by department" value={department} onChange={(e) => { setDepartment(e.target.value); setPage(0); }} placeholder="Department…" className="text-xs" />
          </div>
          {showCreate && (
            <CreateUserForm
              roles={allRoles.data?.items ?? []}
              pending={create.isPending}
              error={create.isError ? create.error : null}
              onSubmit={(payload) => create.mutate(payload)}
            />
          )}
          {users.isPending ? (
            <Skeleton lines={5} />
          ) : users.isError ? (
            <ErrorState title={errTitle("Users unavailable", users.error)} error={users.error} onRetry={() => void users.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No users" description="No accounts match these filters." />
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <caption className="sr-only">Platform users with status, roles, and last login</caption>
                  <THead>
                    <TR>
                      <TH scope="col">User</TH>
                      <TH scope="col">Email</TH>
                      <TH scope="col">Status</TH>
                      <TH scope="col">Roles</TH>
                      <TH scope="col">Last login</TH>
                      <TH scope="col"><span className="sr-only">Actions</span></TH>
                    </TR>
                  </THead>
                  <TBody>
                    {list.map((u) => (
                      <TR key={u.user_id}>
                        <TD className="font-medium">
                          {str(u.full_name) || u.username}
                          <span className="meta-text block font-mono">@{u.username}</span>
                        </TD>
                        <TD className="text-[11px]">{u.email}</TD>
                        <TD><Badge tone={u.status === "active" ? "success" : u.status === "suspended" || u.status === "disabled" ? "danger" : "warning"} size="sm">{u.status}</Badge></TD>
                        <TD>
                          <span className="text-[11px] text-slate-600 dark:text-slate-300">
                            {arr<string>(u.role_ids).map(roleName).join(", ") || "no roles"}
                          </span>
                        </TD>
                        <TD className="whitespace-nowrap text-[11px]">{u.last_login_at ? formatRelative(u.last_login_at) : "never"}</TD>
                        <TD>
                          <Button variant="ghost" size="sm" onClick={() => setSelectedId(u.user_id)} aria-label={`Inspect user ${u.username}`}>
                            Inspect
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="meta-text">Page {page + 1} · {list.length} shown</span>
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</Button>
                  <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>Next</Button>
                </div>
              </div>
            </>
          )}
        </div>
      </Card>

      {selectedId && (
        <UserDetail
          userId={selectedId}
          roles={(allRoles.data?.items ?? [])}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function CreateUserForm({
  roles,
  pending,
  error,
  onSubmit,
}: {
  roles: AdminRole[];
  pending: boolean;
  error: unknown;
  onSubmit: (payload: Parameters<typeof createUser>[0]) => void;
}) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState<AdminUserStatus>("active");
  const [roleIds, setRoleIds] = useState<string[]>([]);

  const valid = username.trim().length >= 1 && email.trim().length >= 3;
  const toggleRole = (id: string) =>
    setRoleIds((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));

  return (
    <div className="mb-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Create user</h3>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Field label="Username" id="cu-username">
          <Input id="cu-username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Email" id="cu-email">
          <Input id="cu-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Password (optional)" id="cu-password" hint="Hashed server-side; omitted when empty">
          <Input id="cu-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label="Full name (optional)" id="cu-fullname">
          <Input id="cu-fullname" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Department (optional)" id="cu-dept">
          <Input id="cu-dept" value={department} onChange={(e) => setDepartment(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Status" id="cu-status">
          <Select id="cu-status" value={status} onChange={(e) => setStatus(e.target.value as AdminUserStatus)}>
            {["active", "invited", "suspended", "disabled"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
        </Field>
      </div>
      {roles.length > 0 && (
        <fieldset className="mt-2">
          <legend className="meta-text mb-1">Roles (backend registry)</legend>
          <div className="flex flex-wrap gap-1.5">
            {roles.map((r) => {
              const on = roleIds.includes(r.role_id);
              return (
                <button
                  key={r.role_id}
                  type="button"
                  onClick={() => toggleRole(r.role_id)}
                  aria-pressed={on}
                  title={r.description || r.name}
                  className={on
                    ? "rounded-full bg-brand-500 px-2.5 py-1 text-xs font-medium text-white"
                    : "rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300"}
                >
                  {r.name}
                </button>
              );
            })}
          </div>
        </fieldset>
      )}
      <div className="mt-3">
        <Button
          variant="primary"
          size="sm"
          loading={pending}
          disabled={pending || !valid}
          onClick={() =>
            onSubmit({
              username: username.trim(),
              email: email.trim(),
              password: password || undefined,
              full_name: fullName.trim() || undefined,
              department: department.trim() || undefined,
              status,
              role_ids: roleIds.length > 0 ? roleIds : undefined,
            })
          }
        >
          Create user
        </Button>
      </div>
      {Boolean(error) && (
        <div className="mt-2">
          <ErrorState title={errTitle("User creation failed", error)} error={error} />
        </div>
      )}
    </div>
  );
}

function UserDetail({ userId, roles, onClose }: { userId: string; roles: AdminRole[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const detail = useQuery({ queryKey: adminKeys.user(userId), queryFn: () => getUser(userId) });
  const [email, setEmail] = useState<string | null>(null);
  const [fullName, setFullName] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [status, setStatus] = useState<AdminUserStatus | null>(null);
  const [grantRoleId, setGrantRoleId] = useState("");
  const [permCode, setPermCode] = useState("");
  const [checkResult, setCheckResult] = useState<Awaited<ReturnType<typeof checkRBAC>> | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: [...adminKeys.all, "users"] });
    void qc.invalidateQueries({ queryKey: adminKeys.user(userId) });
    void qc.invalidateQueries({ queryKey: adminKeys.stats() });
  };

  const update = useMutation({
    mutationFn: (payload: Parameters<typeof updateUser>[1]) => updateUser(userId, payload),
    onSuccess: (u) => {
      invalidate();
      setEmail(null);
      setFullName(null);
      setDepartment(null);
      setStatus(null);
      toast.push({ title: "User updated", description: u.username, tone: "success" });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteUser(userId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...adminKeys.all, "users"] });
      void qc.invalidateQueries({ queryKey: adminKeys.stats() });
      toast.push({ title: "User deleted", description: userId, tone: "success" });
      onClose();
    },
  });
  const grant = useMutation({
    mutationFn: (roleId: string) => grantRole(userId, roleId),
    onSuccess: (u) => {
      invalidate();
      setGrantRoleId("");
      toast.push({ title: "Role granted", description: u.username, tone: "success" });
    },
  });
  const revoke = useMutation({
    mutationFn: (roleId: string) => revokeRole(userId, roleId),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "Role revoked", description: userId, tone: "success" });
    },
  });
  const check = useMutation({
    mutationFn: (code: string) => checkRBAC(userId, code),
    onSuccess: (r) => setCheckResult(r),
  });

  if (detail.isPending) {
    return (
      <Card padding="md" aria-label="User loading">
        <Skeleton className="h-6 w-1/3" />
        <div className="mt-2"><Skeleton lines={3} /></div>
      </Card>
    );
  }
  if (detail.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title={errTitle("User unavailable", detail.error)}
          error={detail.error}
          onRetry={() => void detail.refetch()}
          action={<Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}
        />
      </Card>
    );
  }

  const u: AdminUser = detail.data;
  const roleName = (id: string) => roles.find((r) => r.role_id === id)?.name ?? id;
  const dirtyProfile =
    (email !== null && email !== (u.email ?? "")) ||
    (fullName !== null && fullName !== (u.full_name ?? "")) ||
    (department !== null && department !== (u.department ?? ""));
  const dirtyStatus = status !== null && status !== u.status;

  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">
            {str(u.full_name) || u.username} <span className="font-mono font-normal text-slate-500">@{u.username}</span>
          </h3>
          <Badge tone={u.status === "active" ? "success" : u.status === "suspended" || u.status === "disabled" ? "danger" : "warning"} size="sm">
            {u.status}
          </Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>Close</Button>
        </div>
        <dl className="meta-text mt-1 space-y-0.5">
          <div>User ID: <span className="font-mono">{u.user_id}</span></div>
          <div>Email: {u.email}</div>
          {str(u.department) && <div>Department: {u.department}</div>}
          <div>Last login: {u.last_login_at ? formatRelative(u.last_login_at) : "never recorded"}</div>
          <div>Created: {u.created_at ? formatRelative(u.created_at) : "time unknown"}</div>
        </dl>

        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-slate-900 dark:text-white">Profile & status</h4>
            <div className="mt-2 space-y-2">
              <Field label="Email" id={`u-email-${u.user_id}`}>
                <Input id={`u-email-${u.user_id}`} value={email ?? u.email ?? ""} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Field label="Full name" id={`u-name-${u.user_id}`}>
                <Input id={`u-name-${u.user_id}`} value={fullName ?? u.full_name ?? ""} onChange={(e) => setFullName(e.target.value)} />
              </Field>
              <Field label="Department" id={`u-dept-${u.user_id}`}>
                <Input id={`u-dept-${u.user_id}`} value={department ?? u.department ?? ""} onChange={(e) => setDepartment(e.target.value)} />
              </Field>
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Status" id={`u-status-${u.user_id}`}>
                  <Select id={`u-status-${u.user_id}`} value={status ?? u.status} onChange={(e) => setStatus(e.target.value as AdminUserStatus)}>
                    {["active", "invited", "suspended", "disabled"].map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </Select>
                </Field>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={update.isPending}
                  disabled={update.isPending || (!dirtyProfile && !dirtyStatus)}
                  onClick={() =>
                    update.mutate({
                      ...(email !== null && email !== u.email ? { email } : {}),
                      ...(fullName !== null && fullName !== (u.full_name ?? "") ? { full_name: fullName } : {}),
                      ...(department !== null && department !== (u.department ?? "") ? { department } : {}),
                      ...(dirtyStatus && status ? { status } : {}),
                    })
                  }
                >
                  Save changes
                </Button>
              </div>
              {update.isError && <ErrorState title={errTitle("Update failed", update.error)} error={update.error} />}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-slate-900 dark:text-white">Roles ({arr<string>(u.role_ids).length})</h4>
            <ul className="mt-2 space-y-1">
              {arr<string>(u.role_ids).length === 0 && <li className="meta-text">No roles assigned.</li>}
              {arr<string>(u.role_ids).map((rid) => (
                <li key={rid} className="flex items-center gap-2 text-xs">
                  <Badge size="sm">{roleName(rid)}</Badge>
                  <span className="meta-text font-mono">{rid}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={revoke.isPending}
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(rid)}
                    aria-label={`Revoke role ${roleName(rid)} from ${u.username}`}
                  >
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
            <div className="mt-2 flex items-end gap-2">
              <Field label="Grant role" id={`u-grant-${u.user_id}`}>
                <Select id={`u-grant-${u.user_id}`} value={grantRoleId} onChange={(e) => setGrantRoleId(e.target.value)}>
                  <option value="">Select role…</option>
                  {roles.filter((r) => !arr(u.role_ids).includes(r.role_id)).map((r) => (
                    <option key={r.role_id} value={r.role_id}>{r.name}</option>
                  ))}
                </Select>
              </Field>
              <Button variant="secondary" size="sm" loading={grant.isPending} disabled={grant.isPending || !grantRoleId} onClick={() => grant.mutate(grantRoleId)}>
                Grant
              </Button>
            </div>
            {(grant.isError || revoke.isError) && (
              <div className="mt-2">
                <ErrorState title={errTitle("Role change failed", grant.error ?? revoke.error)} error={grant.error ?? revoke.error} />
              </div>
            )}

            <h4 className="mt-4 text-xs font-semibold text-slate-900 dark:text-white">Permission check</h4>
            <p className="meta-text mb-1">Evaluates this user against the backend RBAC rules.</p>
            <div className="flex items-end gap-2">
              <Field label="Permission code" id={`u-perm-${u.user_id}`}>
                <Input id={`u-perm-${u.user_id}`} value={permCode} onChange={(e) => setPermCode(e.target.value)} placeholder="documents:read" />
              </Field>
              <Button variant="ghost" size="sm" loading={check.isPending} disabled={check.isPending || !permCode.trim()} onClick={() => check.mutate(permCode.trim())}>
                Check
              </Button>
            </div>
            {check.isError && (
              <div className="mt-2">
                <ErrorState title={errTitle("Check failed", check.error)} error={check.error} />
              </div>
            )}
            {checkResult && (
              <div className="mt-2 rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-700" role="status">
                <Badge tone={checkResult.allowed ? "success" : "danger"} size="sm">
                  {checkResult.allowed ? "Allowed" : "Denied"}
                </Badge>
                <p className="meta-text mt-1">
                  {str(checkResult.reason) || "no reason given"}
                  {arr(checkResult.matched_roles).length > 0 && ` · via ${arr(checkResult.matched_roles).join(", ")}`}
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
          <h4 className="text-xs font-semibold text-red-700 dark:text-red-300">Delete user</h4>
          <p className="meta-text mb-2 mt-0.5">
            Permanent and immediate. The backend performs no self-delete or
            usage guard — confirm deliberately.
          </p>
          <Button
            variant="danger"
            size="sm"
            loading={remove.isPending}
            disabled={remove.isPending}
            onClick={() => {
              if (confirmDelete) {
                remove.mutate();
              } else {
                setConfirmDelete(true);
              }
            }}
          >
            {confirmDelete ? `Confirm deletion of ${u.username}` : "Delete user"}
          </Button>
          {remove.isError && (
            <div className="mt-2">
              <ErrorState title={errTitle("Deletion failed", remove.error)} error={remove.error} />
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ─── roles ────────────────────────────────────────────────────────── */

function RolesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [textQuery, setTextQuery] = useState("");
  const [builtIn, setBuiltIn] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const listQuery = useMemo(
    () => ({
      built_in: builtIn === "" ? undefined : builtIn === "true",
      text_query: textQuery.trim() || undefined,
      page: page + 1,
      page_size: ROLE_PAGE_SIZE,
    }),
    [builtIn, textQuery, page]
  );
  const roles = useQuery({
    queryKey: adminKeys.roles(listQuery),
    queryFn: () => getRoles(listQuery),
  });

  const create = useMutation({
    mutationFn: createRole,
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: [...adminKeys.all, "roles"] });
      void qc.invalidateQueries({ queryKey: adminKeys.stats() });
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
      setSelectedId(r.role_id);
      toast.push({ title: "Role created", description: r.name, tone: "success" });
    },
  });

  const list = roles.data?.items ?? [];
  const shortPage = list.length < ROLE_PAGE_SIZE;

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Roles"
          description="Backend role registry with permission bundles"
          actions={
            <Button variant="secondary" size="sm" onClick={() => setShowCreate((v) => !v)} aria-expanded={showCreate}>
              {showCreate ? "Close form" : "New role"}
            </Button>
          }
        />
        <div className="card-body" aria-live="polite">
          <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Input aria-label="Search roles" value={textQuery} onChange={(e) => { setTextQuery(e.target.value); setPage(0); }} placeholder="Search name…" className="text-xs" />
            <Select aria-label="Filter roles by origin" value={builtIn} onChange={(e) => { setBuiltIn(e.target.value); setPage(0); }} className="text-xs">
              <option value="">Built-in and custom</option>
              <option value="true">Built-in only</option>
              <option value="false">Custom only</option>
            </Select>
          </div>
          {showCreate && (
            <div className="mb-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Create role</h3>
              <p className="meta-text mb-2 mt-0.5">Permissions are edited after creation, in the role detail.</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Field label="Name" id="cr-name">
                  <Input id="cr-name" value={newName} onChange={(e) => setNewName(e.target.value)} />
                </Field>
                <Field label="Description (optional)" id="cr-desc">
                  <Input id="cr-desc" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
                </Field>
              </div>
              <div className="mt-2">
                <Button
                  variant="primary"
                  size="sm"
                  loading={create.isPending}
                  disabled={create.isPending || newName.trim().length < 1}
                  onClick={() => create.mutate({ name: newName.trim(), description: newDesc.trim() || undefined })}
                >
                  Create role
                </Button>
              </div>
              {create.isError && (
                <div className="mt-2">
                  <ErrorState title={errTitle("Role creation failed", create.error)} error={create.error} />
                </div>
              )}
            </div>
          )}
          {roles.isPending ? (
            <Skeleton lines={4} />
          ) : roles.isError ? (
            <ErrorState title={errTitle("Roles unavailable", roles.error)} error={roles.error} onRetry={() => void roles.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No roles" description="No roles match these filters." />
          ) : (
            <>
              <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {list.map((r) => (
                  <li key={r.role_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.role_id)}
                      aria-pressed={selectedId === r.role_id}
                      className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{r.name}</span>
                        {r.built_in && <Badge size="sm">built-in</Badge>}
                        <span className="meta-text ml-auto">{arr(r.permissions).length} permission(s) · {r.user_count} user(s)</span>
                      </div>
                      {str(r.description) && <p className="meta-text mt-1">{r.description}</p>}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="meta-text">Page {page + 1} · {list.length} shown</span>
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</Button>
                  <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>Next</Button>
                </div>
              </div>
            </>
          )}
        </div>
      </Card>

      {selectedId && <RoleDetail roleId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}

function RoleDetail({ roleId, onClose }: { roleId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const detail = useQuery({ queryKey: adminKeys.role(roleId), queryFn: () => getRole(roleId) });
  const [perms, setPerms] = useState<AdminPermission[] | null>(null);
  const [newCode, setNewCode] = useState("");
  const [newResource, setNewResource] = useState("");
  const [newAction, setNewAction] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: [...adminKeys.all, "roles"] });
    void qc.invalidateQueries({ queryKey: adminKeys.role(roleId) });
    void qc.invalidateQueries({ queryKey: adminKeys.stats() });
  };

  const save = useMutation({
    mutationFn: (permissions: AdminPermission[]) => updateRolePermissions(roleId, permissions),
    onSuccess: () => {
      invalidate();
      setPerms(null);
      toast.push({ title: "Permissions saved", description: roleId, tone: "success" });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteRole(roleId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...adminKeys.all, "roles"] });
      void qc.invalidateQueries({ queryKey: adminKeys.stats() });
      toast.push({ title: "Role deleted", description: roleId, tone: "success" });
      onClose();
    },
  });

  if (detail.isPending) {
    return (
      <Card padding="md" aria-label="Role loading">
        <Skeleton className="h-6 w-1/3" />
        <div className="mt-2"><Skeleton lines={3} /></div>
      </Card>
    );
  }
  if (detail.isError) {
    return (
      <Card padding="md">
        <ErrorState
          title={errTitle("Role unavailable", detail.error)}
          error={detail.error}
          onRetry={() => void detail.refetch()}
          action={<Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}
        />
      </Card>
    );
  }

  const r = detail.data;
  const editing = perms ?? arr(r.permissions);
  const dirty = perms !== null;

  const addPermission = () => {
    if (!newCode.trim()) return;
    setPerms([
      ...editing,
      {
        permission_id: `local-${Date.now()}`,
        code: newCode.trim(),
        description: newDesc.trim(),
        resource: newResource.trim(),
        action: newAction.trim(),
      },
    ]);
    setNewCode("");
    setNewResource("");
    setNewAction("");
    setNewDesc("");
  };

  return (
    <Card padding="none">
      <div className="card-body">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">{r.name}</h3>
          {r.built_in ? (
            <Badge size="sm">built-in (cannot be deleted)</Badge>
          ) : (
            <Badge size="sm">custom</Badge>
          )}
          <span className="meta-text">{r.user_count} user(s)</span>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>Close</Button>
        </div>
        {str(r.description) && <p className="meta-text mt-1">{r.description}</p>}
        <p className="meta-text mt-1">Role ID: <span className="font-mono">{r.role_id}</span></p>

        <h4 className="mt-4 text-xs font-semibold text-slate-900 dark:text-white">
          Permissions ({editing.length}) — saving replaces the full list
        </h4>
        {editing.length === 0 ? (
          <p className="meta-text mt-1">This role grants no permissions.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {editing.map((p, i) => (
              <li key={p.permission_id || `perm-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-800">
                <span className="font-mono font-medium text-slate-900 dark:text-slate-100">{p.code}</span>
                {(p.resource || p.action) && (
                  <span className="meta-text">{[p.resource, p.action].filter(Boolean).join(" · ")}</span>
                )}
                {str(p.description) && <span className="meta-text w-full">{p.description}</span>}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  onClick={() => setPerms(editing.filter((_, j) => j !== i))}
                  aria-label={`Remove permission ${p.code}`}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Field label="Permission code" id={`np-code-${r.role_id}`}>
            <Input id={`np-code-${r.role_id}`} value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="documents:read" />
          </Field>
          <Field label="Description (optional)" id={`np-desc-${r.role_id}`}>
            <Input id={`np-desc-${r.role_id}`} value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
          </Field>
          <Field label="Resource (optional)" id={`np-res-${r.role_id}`}>
            <Input id={`np-res-${r.role_id}`} value={newResource} onChange={(e) => setNewResource(e.target.value)} placeholder="documents" />
          </Field>
          <Field label="Action (optional)" id={`np-action-${r.role_id}`}>
            <Input id={`np-action-${r.role_id}`} value={newAction} onChange={(e) => setNewAction(e.target.value)} placeholder="read" />
          </Field>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" disabled={!newCode.trim()} onClick={addPermission}>
            Add permission
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={save.isPending}
            disabled={save.isPending || !dirty}
            onClick={() => save.mutate(editing)}
          >
            Save permissions
          </Button>
        </div>
        {save.isError && (
          <div className="mt-2">
            <ErrorState title={errTitle("Permission save failed", save.error)} error={save.error} />
          </div>
        )}

        {!r.built_in && (
          <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
            <h4 className="text-xs font-semibold text-red-700 dark:text-red-300">Delete role</h4>
            <p className="meta-text mb-2 mt-0.5">Permanent. Users holding this role keep their other roles; the deleted ID simply stops resolving.</p>
            <Button
              variant="danger"
              size="sm"
              loading={remove.isPending}
              disabled={remove.isPending}
              onClick={() => {
                if (confirmDelete) {
                  remove.mutate();
                } else {
                  setConfirmDelete(true);
                }
              }}
            >
              {confirmDelete ? `Confirm deletion of ${r.name}` : "Delete role"}
            </Button>
            {remove.isError && (
              <div className="mt-2">
                <ErrorState title={errTitle("Deletion failed", remove.error)} error={remove.error} />
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ─── settings ─────────────────────────────────────────────────────── */

function SettingsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [newKey, setNewKey] = useState("");
  const [newType, setNewType] = useState("string");
  const [newValue, setNewValue] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newCategory, setNewCategory] = useState("general");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const settings = useQuery({ queryKey: adminKeys.settings(), queryFn: getSettings });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: adminKeys.settings() });
    void qc.invalidateQueries({ queryKey: adminKeys.stats() });
  };

  const save = useMutation({
    mutationFn: ({ key, value, description }: { key: string; value: unknown; description?: string }) =>
      setSetting(key, { value, description }),
    onSuccess: (s) => {
      invalidate();
      setEditingKey(null);
      toast.push({ title: "Setting saved", description: s.key, tone: "success" });
    },
  });
  const create = useMutation({
    mutationFn: () => {
      const { value, error } = coerceSettingValue(newValue, newType);
      if (error) throw new Error(error);
      return setSetting(newKey.trim(), {
        value,
        description: newDesc.trim() || undefined,
        category: newCategory.trim() || undefined,
      });
    },
    onSuccess: (s) => {
      invalidate();
      setNewKey("");
      setNewValue("");
      setNewDesc("");
      setNewCategory("general");
      setShowCreate(false);
      toast.push({ title: "Setting created", description: s.key, tone: "success" });
    },
  });
  const remove = useMutation({
    mutationFn: (key: string) => deleteSetting(key),
    onSuccess: (_, key) => {
      invalidate();
      setConfirmDelete(null);
      toast.push({ title: "Setting deleted", description: key, tone: "success" });
    },
  });

  const startEdit = (s: PlatformSetting) => {
    setEditingKey(s.key);
    // Secrets are never displayed: editing one always starts from empty.
    setEditText(s.is_secret ? "" : settingToText(s.value, s.value_type));
  };

  const submitEdit = (s: PlatformSetting) => {
    if (save.isPending) return;
    const { value, error } = coerceSettingValue(editText, s.value_type);
    if (error) {
      toast.push({ title: "Invalid value", description: error, tone: "danger" });
      return;
    }
    save.mutate({ key: s.key, value });
  };

  const list = settings.data ?? [];

  return (
    <div className="space-y-4">
      <Card padding="none">
        <CardHeader
          title="Platform settings"
          description="Typed key/value configuration. Secret values are never displayed."
          actions={
            <Button variant="secondary" size="sm" onClick={() => setShowCreate((v) => !v)} aria-expanded={showCreate}>
              {showCreate ? "Close form" : "New setting"}
            </Button>
          }
        />
        <div className="card-body" aria-live="polite">
          {showCreate && (
            <div className="mb-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Create setting</h3>
              <p className="meta-text mb-2 mt-0.5">New settings are non-secret; secrecy cannot be toggled from this UI.</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Field label="Key" id="ns-key">
                  <Input id="ns-key" value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="search.top_k" />
                </Field>
                <Field label="Type" id="ns-type">
                  <Select id="ns-type" value={newType} onChange={(e) => setNewType(e.target.value)}>
                    {VALUE_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Value" id="ns-value" hint="Validated against the selected type">
                  <Input id="ns-value" value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder="10" />
                </Field>
                <Field label="Category (optional)" id="ns-category">
                  <Input id="ns-category" value={newCategory} onChange={(e) => setNewCategory(e.target.value)} />
                </Field>
                <Field label="Description (optional)" id="ns-desc" className="sm:col-span-2">
                  <Input id="ns-desc" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
                </Field>
              </div>
              <div className="mt-2">
                <Button
                  variant="primary"
                  size="sm"
                  loading={create.isPending}
                  disabled={create.isPending || newKey.trim().length < 1}
                  onClick={() => create.mutate()}
                >
                  Create setting
                </Button>
              </div>
              {create.isError && (
                <div className="mt-2">
                  <ErrorState title={errTitle("Setting creation failed", create.error)} error={create.error} />
                </div>
              )}
            </div>
          )}
          {settings.isPending ? (
            <Skeleton lines={4} />
          ) : settings.isError ? (
            <ErrorState title={errTitle("Settings unavailable", settings.error)} error={settings.error} onRetry={() => void settings.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState title="No settings" description="No platform settings are defined." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <caption className="sr-only">Platform settings with type, value or secrecy, and update time</caption>
                <THead>
                  <TR>
                    <TH scope="col">Key</TH>
                    <TH scope="col">Value</TH>
                    <TH scope="col">Type</TH>
                    <TH scope="col">Category</TH>
                    <TH scope="col">Updated</TH>
                    <TH scope="col"><span className="sr-only">Actions</span></TH>
                  </TR>
                </THead>
                <TBody>
                  {list.map((s) => {
                    const editing = editingKey === s.key;
                    return (
                      <TR key={s.key}>
                        <TD className="font-mono text-[11px] font-medium">
                          {s.key}
                          {str(s.description) && <span className="meta-text block font-sans">{s.description}</span>}
                        </TD>
                        <TD className="max-w-[240px] text-[11px]">
                          {editing ? (
                            <Input
                              aria-label={`Value for ${s.key}`}
                              type={s.is_secret ? "password" : undefined}
                              value={editText}
                              onChange={(e) => setEditText(e.target.value)}
                              placeholder={s.is_secret ? "Enter new value (current is hidden)" : undefined}
                              className="font-mono text-[11px]"
                            />
                          ) : s.is_secret ? (
                            <span className="meta-text">hidden (secret) — enter a new value to replace it</span>
                          ) : (
                            <span className="break-all font-mono">{settingToText(s.value, s.value_type) || "—"}</span>
                          )}
                        </TD>
                        <TD><Badge size="sm">{s.value_type}</Badge></TD>
                        <TD className="text-[11px]">{s.category}</TD>
                        <TD className="whitespace-nowrap text-[10px]">
                          {s.updated_at ? formatRelative(s.updated_at) : "—"}
                          {str(s.updated_by) ? <span className="meta-text block">by {s.updated_by}</span> : null}
                        </TD>
                        <TD>
                          <div className="flex gap-1">
                            {editing ? (
                              <>
                                <Button variant="secondary" size="sm" loading={save.isPending} disabled={save.isPending} onClick={() => submitEdit(s)}>
                                  Save
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => setEditingKey(null)}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <Button variant="ghost" size="sm" onClick={() => startEdit(s)}>
                                Edit
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              loading={remove.isPending}
                              disabled={remove.isPending}
                              onClick={() => {
                                if (confirmDelete === s.key) {
                                  remove.mutate(s.key);
                                } else {
                                  setConfirmDelete(s.key);
                                }
                              }}
                              aria-label={confirmDelete === s.key ? `Confirm deletion of setting ${s.key}` : `Delete setting ${s.key}`}
                            >
                              {confirmDelete === s.key ? "Confirm" : "Delete"}
                            </Button>
                          </div>
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
            </div>
          )}
          {(save.isError || remove.isError) && (
            <div className="mt-2">
              <ErrorState title={errTitle("Setting change failed", save.error ?? remove.error)} error={save.error ?? remove.error} />
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
