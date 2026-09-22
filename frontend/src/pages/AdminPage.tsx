import { Card, CardHeader } from "@/components/ui/Card";
import { Metric } from "@/components/ui/Metric";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useQuery } from "@tanstack/react-query";
import { getAdminOverview, getAdminStats, getUsers, getRoles } from "@/services/api/adminApi";
import { formatRelative } from "@/lib/format";
import { adminKeys } from "@/lib/queryKeys";
import { toAdminRoleView, toAdminUserView } from "@/adapters/governance";

export function AdminPage() {
  const overview = useQuery({ queryKey: adminKeys.overview(), queryFn: getAdminOverview });
  const stats = useQuery({ queryKey: adminKeys.stats(), queryFn: getAdminStats });
  const users = useQuery({ queryKey: adminKeys.users(), queryFn: getUsers });
  const roles = useQuery({ queryKey: adminKeys.roles(), queryFn: getRoles });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="page-title">
          Admin Console
        </h2>
        <p className="page-description">
          Users, roles, and platform overview.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric
          label="Users"
          value={stats.data?.total_users ?? overview.data?.total_users ?? "—"}
          hint={
            stats.data
              ? `${stats.data.active_users} active`
              : undefined
          }
        />
        <Metric
          label="Roles"
          value={stats.data?.total_roles ?? "—"}
        />
        <Metric
          label="Decisions"
          value={overview.data?.total_decisions ?? "—"}
        />
        <Metric
          label="Compliance rate"
          value={overview.data ? `${Math.round(overview.data.compliance_rate * 100)}%` : "—"}
        />
      </section>

      <Card padding="none">
        <CardHeader title="Users" description="All platform users" />
        <div className="card-body">
          {users.isLoading ? (
            <Skeleton lines={5} />
          ) : users.isError ? (
            <ErrorState error={users.error} onRetry={() => users.refetch()} />
          ) : !users.data?.items?.length ? (
            <EmptyState title="No users" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Email</TH>
                  <TH>Roles</TH>
                  <TH>Status</TH>
                  <TH>Last login</TH>
                </TR>
              </THead>
              <TBody>
                {(users.data?.items ?? []).map(toAdminUserView).map((u) => (
                  <TR key={u.id}>
                    <TD>
                      <p className="font-semibold text-slate-900 dark:text-slate-100">
                        {u.displayName}
                      </p>
                    </TD>
                    <TD>{u.email}</TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        <Badge tone="brand" size="sm">
                          {u.roleCount} roles
                        </Badge>
                      </div>
                    </TD>
                    <TD>
                      <Badge
                        tone={
                          u.status === "active"
                            ? "success"
                            : u.status === "suspended"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {u.status}
                      </Badge>
                    </TD>
                    <TD>{formatRelative(u.lastLoginMillis)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Roles" description="Role definitions" />
        <div className="card-body">
          {roles.isLoading ? (
            <Skeleton lines={3} />
          ) : !roles.data?.items?.length ? (
            <EmptyState title="No roles" />
          ) : (
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {(roles.data?.items ?? []).map(toAdminRoleView).map((r) => (
                <li
                  key={r.id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {r.name}
                    </span>
                    <Badge tone="brand" size="sm">
                      {r.memberCount} members
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                    {r.permissionCount} permissions
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}

