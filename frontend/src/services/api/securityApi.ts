import { api } from "@/lib/api";

/**
 * Security reference data. Backend: app/security/api.py (/security/*).
 * Read-only reference surface: built-in roles and their permission grants.
 */
export interface SecurityRoleGrants {
  roles: Record<string, string[]>;
  permissions: string[];
}

export async function getRoleGrants(): Promise<SecurityRoleGrants> {
  return api.get<SecurityRoleGrants>("/security/roles");
}
