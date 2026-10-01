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

/** GET /admin/dashboard/analytics — the series behind the dashboard charts. */
export type MerchantGrowthPoint = { label: string; month: string; onboarded: number; merchants: number };
export type OtpDayPoint = { label: string; day: string; success: number; failed: number };
export type ActivityDayPoint = { label: string; day: string; sign_ins: number };
export type ChannelPoint = { channel: string; sessions: number };
export type StatusCount = { status: string; count: number };

export type DashboardAnalytics = {
  merchant_growth: MerchantGrowthPoint[];
  otp_attempts: OtpDayPoint[];
  user_activity: ActivityDayPoint[];
  login_channels: ChannelPoint[];
  kyc_status: StatusCount[];
  otp_today_total: number;
  otp_today_success_rate: number;
  kyc_pending: number;
};

export type DashboardAnalyticsParams = { days: number; months: number };

export async function getAdminDashboardAnalytics(params: DashboardAnalyticsParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<DashboardAnalytics>("/admin/dashboard/analytics", { params, signal });
  return data;
}
