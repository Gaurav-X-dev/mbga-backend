import { apiClient } from "./client";

/** GET /admin/dashboard/summary */
export type AdminDashboardSummary = {
  users: number;
  active_users: number;
  blocked_users: number;
  roles: number;
  active_roles: number;
  permissions: number;
  active_permissions: number;
  active_sessions: number;
  audit_logs: number;
};

export async function getAdminDashboardSummary(signal?: AbortSignal) {
  const { data } = await apiClient.get<AdminDashboardSummary>("/admin/dashboard/summary", { signal });
  return data;
}
