/**
 * Auth contracts. Backend: app/security/api.py (routes) + LoginRequest /
 * LoginResponse / TokenResponse / SignupRequest / SignupResponse / MeResponse.
 *
 * Critical asymmetry (verified): /login and /signup return LoginResponse
 * (WITH user), but /refresh returns TokenResponse (WITHOUT user).
 */
export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthUser {
  user_id: string;
  username: string;
  email: string;
  full_name: string;
  roles: string[];
  rbac_roles: string[];
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  access_expires_at: string;
  refresh_expires_at: string;
  user: AuthUser;
}

/** POST /security/auth/refresh — same envelope MINUS user. */
export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  access_expires_at: string;
  refresh_expires_at: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  full_name?: string;
  username?: string;
}

/** POST /security/auth/signup (201) — login envelope; new users get roles [] / rbac_roles ["viewer"]. */
export type SignupResponse = LoginResponse;

export interface MeResponse {
  subject_id: string;
  roles: string[];
  scopes: string[];
  permissions: string[];
}
