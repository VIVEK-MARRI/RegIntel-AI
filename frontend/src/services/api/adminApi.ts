import { api, encodePathSegment } from "@/lib/api";
import type {
  AdminOverview,
  AdminRole,
  AdminRoleCreate,
  AdminRoleListQuery,
  AdminStats,
  AdminUser,
  AdminUserCreate,
  AdminUserListQuery,
  AdminUserUpdate,
  PaginatedAdminRoles,
  PaginatedAdminUsers,
  PlatformSetting,
  PlatformSettingUpdate,
  RBACCheck,
} from "@/types/api/admin";
import type { AdminPermission } from "@/types/api/admin";

export async function getAdminOverview(): Promise<AdminOverview> {
  return api.get<AdminOverview>("/admin/overview");
}

export async function getAdminStats(): Promise<AdminStats> {
  return api.get<AdminStats>("/admin/stats");
}

export async function getUsers(query?: AdminUserListQuery): Promise<PaginatedAdminUsers> {
  return api.get<PaginatedAdminUsers>("/admin/users", { query });
}

export async function getUser(id: string): Promise<AdminUser> {
  return api.get<AdminUser>(`/admin/users/${encodePathSegment(id)}`);
}

export async function createUser(payload: AdminUserCreate): Promise<AdminUser> {
  return api.post<AdminUser>("/admin/users", payload);
}

export async function updateUser(id: string, payload: AdminUserUpdate): Promise<AdminUser> {
  return api.patch<AdminUser>(`/admin/users/${encodePathSegment(id)}`, payload);
}

export async function deleteUser(id: string): Promise<void> {
  await api.del(`/admin/users/${encodePathSegment(id)}`);
}

export async function grantRole(userId: string, roleId: string): Promise<AdminUser> {
  return api.post<AdminUser>(
    `/admin/users/${encodePathSegment(userId)}/roles/${encodePathSegment(roleId)}`
  );
}

export async function revokeRole(userId: string, roleId: string): Promise<void> {
  await api.del(
    `/admin/users/${encodePathSegment(userId)}/roles/${encodePathSegment(roleId)}`
  );
}

export async function getRoles(query?: AdminRoleListQuery): Promise<PaginatedAdminRoles> {
  return api.get<PaginatedAdminRoles>("/admin/roles", { query });
}

export async function getRole(id: string): Promise<AdminRole> {
  return api.get<AdminRole>(`/admin/roles/${encodePathSegment(id)}`);
}

export async function createRole(payload: AdminRoleCreate): Promise<AdminRole> {
  return api.post<AdminRole>("/admin/roles", payload);
}

/** Full-list replacement: the backend overwrites role.permissions. */
export async function updateRolePermissions(
  id: string,
  permissions: AdminPermission[]
): Promise<AdminRole> {
  return api.patch<AdminRole>(
    `/admin/roles/${encodePathSegment(id)}/permissions`,
    permissions
  );
}

export async function deleteRole(id: string): Promise<void> {
  await api.del(`/admin/roles/${encodePathSegment(id)}`);
}

export async function checkRBAC(userId: string, permission: string): Promise<RBACCheck> {
  return api.get<RBACCheck>(`/admin/rbac/${encodePathSegment(userId)}`, {
    query: { permission },
  });
}

export async function getSettings(): Promise<PlatformSetting[]> {
  return api.get<PlatformSetting[]>("/admin/settings");
}

export async function setSetting(key: string, payload: PlatformSettingUpdate): Promise<PlatformSetting> {
  return api.put<PlatformSetting>(`/admin/settings/${encodePathSegment(key)}`, payload);
}

export async function deleteSetting(key: string): Promise<void> {
  await api.del(`/admin/settings/${encodePathSegment(key)}`);
}

export type { AdminOverview, AdminRole, AdminStats, AdminUser };
