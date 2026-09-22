import { api } from "@/lib/api";
import type {
  LoginRequest,
  LoginResponse,
  MeResponse,
  RefreshResponse,
  SignupRequest,
  SignupResponse,
} from "@/types/api/auth";

export async function login(data: LoginRequest): Promise<LoginResponse> {
  return api.post<LoginResponse>("/security/auth/login", data);
}

export async function signup(data: SignupRequest): Promise<SignupResponse> {
  return api.post<SignupResponse>("/security/auth/signup", data);
}

export async function refreshToken(refresh_token: string): Promise<RefreshResponse> {
  return api.post<RefreshResponse>("/security/auth/refresh", { refresh_token });
}

export async function getMe(): Promise<MeResponse> {
  return api.get<MeResponse>("/security/auth/me");
}
