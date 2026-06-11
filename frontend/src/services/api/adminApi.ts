import { api } from "@/lib/api";
import type { AdminOverview, AdminRole, AdminStats, AdminUser } from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export async function getAdminOverview(): Promise<AdminOverview> {
  return api.get("/admin/overview");
}

export async function getAdminStats(): Promise<AdminStats> {
  return api.get("/admin/stats");
}

export async function getUsers(): Promise<PaginatedResponse<AdminUser>> {
  return api.get("/admin/users");
}

export async function getRoles(): Promise<PaginatedResponse<AdminRole>> {
  return api.get("/admin/roles");
}
