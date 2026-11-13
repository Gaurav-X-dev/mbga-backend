import { apiClient } from "./client";
import { cleanParams } from "./params";

export type ReminderKind = "PROXIMITY" | "INACTIVE" | "PRICING";
export type Rule = {
  enabled: boolean; allowMerchantOverride: boolean; days: number; radiusMeters: number;
  maxLocationAgeSeconds: number; maxAccuracyMeters: number;
  intervalHours: number; maxCount: number; maxSnoozeHours: number; notificationTtlHours: number;
  weekdays: number[]; startHour: number; endHour: number; pushEnabled: boolean;
  includeNeverOrdered: boolean; suppressActiveOrders: boolean;
  customerTypes: string[];
  groupIds: string[]; staffUserIds: string[]; upcomingDays: number; missingRates: boolean;
  staleReview: boolean; title: string; staffTemplate: string; customerTemplate: string;
};
export type RuleView = { kind: ReminderKind; config: Rule; default: Rule; hasOverride: boolean; inherited: boolean };
export type AutomationSettings = { merchantId: string | null; rules: RuleView[]; placeholders: string[];
  customerTypes: Option[]; groups: Option[]; recipients: Option[] };
export type Option = { value: string; label: string };
export type FollowUp = { id: string; merchantId: string; kind: ReminderKind; customerId?: string | null; siteId?: string | null;
  subject: string; status: string; reason?: string | null; context: Record<string, unknown>;
  reminderCount: number; lastSentAt: string | null; nextDueAt: string | null; updatedAt: string };
export type ReminderScope = { merchant: boolean; merchantId?: string };
export function reminderPath(scope: ReminderScope) { return scope.merchant ? "/merchant" : "/admin"; }
function params(scope: ReminderScope) { return scope.merchant ? {} : cleanParams({ merchantId: scope.merchantId }); }
export async function getAutomationSettings(scope: ReminderScope, signal?: AbortSignal) {
  return (await apiClient.get<AutomationSettings>(`${reminderPath(scope)}/settings/automations`, { params: params(scope), signal })).data;
}
export async function saveAutomationRule(scope: ReminderScope, kind: ReminderKind, config: Rule | null) {
  return (await apiClient.patch<AutomationSettings>(`${reminderPath(scope)}/settings/automations/${kind}`, { config }, { params: params(scope) })).data;
}
export async function listReminders(scope: ReminderScope, filters: { kind?: string; status?: string; limit: number; offset: number }, signal?: AbortSignal) {
  return (await apiClient.get<{ items: FollowUp[]; total: number }>(`${reminderPath(scope)}/reminders`, { params: cleanParams({ ...params(scope), ...filters }), signal })).data;
}
export async function updateReminder(scope: ReminderScope, id: string, input: { status: string; snoozeHours?: number; note?: string }) {
  return (await apiClient.patch<FollowUp>(`${reminderPath(scope)}/reminders/${id}`, input, { params: params(scope) })).data;
}
export async function markPricingReviewed(scope: ReminderScope, month: string, note?: string) {
  return (await apiClient.post(`${reminderPath(scope)}/pricing/reviews`, { month, note }, { params: params(scope) })).data;
}
