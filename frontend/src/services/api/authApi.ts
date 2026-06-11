import { api, request } from "@/lib/api";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  access_expires_at: string;
  refresh_expires_at: string;
  user: {
    user_id: string;
    username: string;
    email: string;
    full_name: string;
    roles: string[];
    rbac_roles: string[];
  };
}

export interface MeResponse {
  subject_id: string;
  roles: string[];
  scopes: string[];
  permissions: string[];
}

export function login(data: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/security/auth/login", {
    method: "POST",
    body: data,
  });
}

export function refreshToken(
  refresh_token: string
): Promise<LoginResponse> {
  return request<LoginResponse>("/security/auth/refresh", {
    method: "POST",
    body: { refresh_token },
  });
}

export function getMe(): Promise<MeResponse> {
  return api.get<MeResponse>("/security/auth/me");
}
