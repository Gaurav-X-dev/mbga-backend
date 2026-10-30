import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/credit. Permissions: credit.view, credit.manage, credit.override. */
export type CreditSettings = {
  creditLimitEnabled: boolean;
  remindersEnabled: boolean;
  /** Hours between reminders to the same customer. */
  intervalHours: number;
  /** Reminders sent before they stop. */
  maxCount: number;
  /** No reminders between these hours (IST, 0-23). */
  quietStartHour: number;
  quietEndHour: number;
  /** Remind once usage reaches this % of the limit. */
  thresholdPercent: number;
  /** Minimum gap between "order blocked" pushes to one customer. */
  blockPushCooldownMinutes: number;
  messageTemplate: string;
};

export type CustomerCredit = {
  customerId: string;
  customerName: string;
  /** Human-readable code (e.g. CUS-0042), when the backend sends it. */
  customerCode?: string | null;
  merchantId: string;
  creditEnabled: boolean;
  creditLimit: number;
  creditDays: number | null;
  usedCredit: number;
  availableCredit: number;
  exceeded: boolean;
};

export type CreditReport = { items: CustomerCredit[]; limit: number; offset: number; total?: number };

export type CreditReportParams = { merchantId?: string; exceededOnly?: boolean; limit: number; offset: number };

export type CustomerCreditInput = {
  creditEnabled: boolean;
  creditLimit: number;
  creditDays?: number | null;
  /** At least 5 characters - it goes in the audit trail. */
  reason: string;
};

export type CreditOverride = { id: string; customerId: string; amount: number; expiresAt: string };

/** Loosely typed: the backend owns these shapes and the panel only lists them. */
export type CreditHistory = {
  settingsAudit: Array<Record<string, unknown>>;
  overrides: Array<Record<string, unknown>>;
  notifications: Array<Record<string, unknown>>;
};

export async function getCreditSettings(signal?: AbortSignal) {
  const { data } = await apiClient.get<CreditSettings>("/admin/credit/settings", { signal });
  return data;
}

/** Partial update - send only what changed. */
export async function updateCreditSettings(input: Partial<CreditSettings>) {
  const { data } = await apiClient.patch<CreditSettings>("/admin/credit/settings", input);
  return data;
}

export async function getCreditReport(params: CreditReportParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<CreditReport>("/admin/credit/customers", {
    params: cleanParams({ ...params, exceededOnly: params.exceededOnly || undefined }),
    signal
  });
  return data;
}

export async function updateCustomerCredit(customerId: string, input: CustomerCreditInput) {
  const { data } = await apiClient.patch<CustomerCredit>(`/admin/credit/customers/${encodeURIComponent(customerId)}`, input);
  return data;
}

export async function approveCreditOverride(customerId: string, input: { amount: number; reason: string; validForMinutes: number }) {
  const { data } = await apiClient.post<CreditOverride>(`/admin/credit/customers/${encodeURIComponent(customerId)}/overrides`, input);
  return data;
}

export async function getCreditHistory(customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<CreditHistory>(`/admin/credit/customers/${encodeURIComponent(customerId)}/history`, { signal });
  return data;
}
