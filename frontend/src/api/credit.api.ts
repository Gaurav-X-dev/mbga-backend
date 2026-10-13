import { apiClient } from "./client";

export type CreditSettings = {
  creditLimitEnabled: boolean;
  remindersEnabled: boolean;
  intervalHours: number;
  maxCount: number;
  quietStartHour: number;
  quietEndHour: number;
  thresholdPercent: number;
  blockPushCooldownMinutes: number;
  messageTemplate: string;
};

export type CreditCustomer = {
  customerId: string;
  customerName: string;
  merchantId: string;
  creditEnabled: boolean;
  creditLimit: number;
  creditDays: number | null;
  usedCredit: number;
  availableCredit: number;
  exceeded: boolean;
};

export async function getCreditSettings() {
  return (await apiClient.get<CreditSettings>("/admin/credit/settings")).data;
}

export async function updateCreditSettings(payload: Partial<CreditSettings>) {
  return (await apiClient.patch<CreditSettings>("/admin/credit/settings", payload)).data;
}

export async function listCreditCustomers() {
  return (
    await apiClient.get<{ items: CreditCustomer[] }>("/admin/credit/customers", {
      params: { limit: 200, offset: 0 }
    })
  ).data;
}

export async function updateCustomerCredit(
  customerId: string,
  payload: { creditEnabled: boolean; creditLimit: number; creditDays: number | null; reason: string }
) {
  return (await apiClient.patch(`/admin/credit/customers/${customerId}`, payload)).data;
}
