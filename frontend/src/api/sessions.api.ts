import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/auth/sessions */
export type SessionStatus = "ACTIVE" | "EXPIRED" | "REVOKED";

export type LoginSession = {
  id: string;
  user_id: string;
  user_name: string | null;
  user_mobile: string | null;
  user_role: string | null;
  login_channel: string | null;
  status: SessionStatus;
  device_name: string | null;
  device_type: string | null;
  user_agent: string | null;
  app_version: string | null;
  ip_address: string | null;
  created_at: string | null;
  last_activity_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
};

export type LoginSessionListResponse = {
  items: LoginSession[];
  total: number;
  limit: number;
  offset: number;
};

export type LoginSessionStats = {
  active: number;
  expired: number;
  revoked: number;
  ended_last_24h: number;
};

export type LoginSessionListParams = {
  status?: string;
  login_channel?: string;
  user_id?: string;
  search?: string;
  limit: number;
  offset: number;
};

export async function listLoginSessions(params: LoginSessionListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<LoginSessionListResponse>("/admin/auth/sessions", {
    params: cleanParams(params),
    signal
  });
  return data;
}

export async function getLoginSessionStats(signal?: AbortSignal) {
  const { data } = await apiClient.get<LoginSessionStats>("/admin/auth/sessions/stats", { signal });
  return data;
}

export async function revokeLoginSession(sessionId: string) {
  const { data } = await apiClient.post<LoginSession>(
    `/admin/auth/sessions/${encodeURIComponent(sessionId)}/revoke`
  );
  return data;
}
