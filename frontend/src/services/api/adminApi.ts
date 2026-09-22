import { api } from "@/lib/api";
import type {
  AdminOverview,
  AdminRole,
  AdminStats,
  AdminUser,
  PaginatedAdminRoles,
  PaginatedAdminUsers,
} from "@/types/api/admin";

export async function getAdminOverview(): Promise<AdminOverview> {
  return api.get<AdminOverview>("/admin/overview");
}

export async function getAdminStats(): Promise<AdminStats> {
  return api.get<AdminStats>("/admin/stats");
}

export async function getUsers(): Promise<PaginatedAdminUsers> {
  return api.get<PaginatedAdminUsers>("/admin/users");
}

export async function getRoles(): Promise<PaginatedAdminRoles> {
  return api.get<PaginatedAdminRoles>("/admin/roles");
}

export type { AdminOverview, AdminRole, AdminStats, AdminUser };
