import { apiClient } from "./client";
import { cleanParams } from "./params";

/**
 * Admin channel: /admin/pricing. Merchant-scoped - `merchantId` on every call.
 * `customerPrice` is computed by the backend (base rate + tier markup) and never sent.
 */
export type PriceEntry = {
  cylinderType: string;
  tier: string;
  bpclBaseRate: number;
  tierMarkup: number;
  customerPrice: number;
};

export type PricingMonth = {
  id: string;
  month: string;
  label: string;
  effectiveFrom: string;
  effectiveTo: string;
  status: "ACTIVE" | "DRAFT" | "ARCHIVED";
  gstPercent: number;
  entries?: PriceEntry[];
  updatedBy: string;
  updatedAt: string;
};

export type PriceEntryInput = {
  cylinderType: string;
  tier?: string;
  bpclBaseRate: number;
  tierMarkup: number;
  effectiveFrom?: string | null;
  reason?: string | null;
};

export type PricingChangeLog = {
  id: string;
  pricingMonthId: string;
  cylinderType: string;
  tier: string;
  oldBpclBaseRate?: number | null;
  oldTierMarkup?: number | null;
  oldCustomerPrice?: number | null;
  newBpclBaseRate: number;
  newTierMarkup: number;
  newCustomerPrice: number;
  effectiveFrom: string;
  reason?: string | null;
  changedBy: { id: string; name: string; role: string };
  changedAt: string;
};

export type PricingChangeLogPage = { items: PricingChangeLog[]; page: number; pageSize: number; total: number };

export type PricingChangeLogParams = {
  merchantId: string;
  cylinderType?: string;
  pricingMonthId?: string;
  from?: string;
  to?: string;
  page?: number;
  pageSize?: number;
};

const scoped = (merchantId: string) => ({ params: { merchantId } });

/** Newest first; the current month is opened on first read, carrying last month's rates. */
export async function listPricingMonths(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<PricingMonth[]>("/admin/pricing/months", { ...scoped(merchantId), signal });
  return data;
}

/** A mid-month change: updates the entry and writes an immutable change-log row. */
export async function updatePriceEntry(merchantId: string, pricingMonthId: string, input: PriceEntryInput) {
  const { data } = await apiClient.put<PricingMonth>(
    `/admin/pricing/months/${encodeURIComponent(pricingMonthId)}/entries`,
    { tier: "STANDARD", ...input },
    scoped(merchantId)
  );
  return data;
}

export async function listPricingChangeLogs(params: PricingChangeLogParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<PricingChangeLogPage>("/admin/pricing/change-logs", { params: cleanParams(params), signal });
  return data;
}
