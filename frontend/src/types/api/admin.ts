/**
 * Admin contracts. Backend: app/api/v1/admin.py + app/schemas/admin.py
 * (all schemas extra="forbid"). Timestamps are epoch SECONDS (float).
 */
import type { PaginatedResponse } from "./common";

export interface AdminOverview {
  total_users: number;
  active_users: number;
  total_roles: number;
  total_policies: number;
  total_decisions: number;
  total_audit_records: number;
  total_reports: number;
  total_workflows: number;
  total_reviews: number;
  compliance_rate: number;
  approval_rate: number;
  generated_at: number;
}

export interface AdminStats {
  total_users: number;
  active_users: number;
  suspended_users: number;
  total_roles: number;
  built_in_roles: number;
  total_permissions: number;
  total_settings: number;
  secret_settings: number;
  by_role: Record<string, number>;
  by_user_status: Record<string, number>;
  generated_at: number;
}

export type AdminUserStatus = "active" | "invited" | "suspended" | "disabled";

export interface AdminUser {
  user_id: string;
  username: string;
  email: string;
  password_hash?: string;
  full_name: string;
  role_ids: string[];
  status: AdminUserStatus;
  department?: string | null;
  last_login_at?: number | null;
  created_at: number;
  updated_at: number;
  metadata?: Record<string, unknown>;
}

export interface AdminPermission {
  permission_id: string;
  code: string;
  description: string;
  resource: string;
  action: string;
}

export interface AdminRole {
  role_id: string;
  name: string;
  description: string;
  built_in: boolean;
  permissions: AdminPermission[];
  user_count: number;
  created_at: number;
  updated_at: number;
  tags?: string[];
}

export type PaginatedAdminUsers = PaginatedResponse<AdminUser>;
export type PaginatedAdminRoles = PaginatedResponse<AdminRole>;
