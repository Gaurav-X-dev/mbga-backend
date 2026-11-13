import { apiClient } from "./client";

export type MarketFilters = { pincode: string; customerType: string; cylinderType: string };
export type Timeframe = "7D" | "30D" | "3M" | "1Y" | "CUSTOM";
export type DateRange = { startDate?: string; endDate?: string };
export type DepotAddress = { line1?: string | null; line2?: string | null; city?: string | null; state?: string | null; pincode?: string | null; latitude?: number | null; longitude?: number | null };
export type ExportOptions = MarketFilters & DateRange & { timeframe: Timeframe; format: "CSV" | "XLSX"; dataset: "snapshot" | "comparison" | "history" | "audit"; includeAudit: boolean };
export type Competitor = {
  id: string; name: string; code: string; color: string; iconName: string;
  status: "ACTIVE" | "INACTIVE"; notes: string | null; updatedAt: string; depotAddress?: DepotAddress | null;
};
export type MarketSnapshot = {
  mbgaPrice: number; avgCompetitorPrice: number; difference: number;
  differencePercentage: number; isLower: boolean; cylinderType: string; cylinderLabel: string; hasCompetitorQuotes?: boolean; competitorQuoteCount?: number;
};
export type ComparisonRow = {
  competitorId: string; name: string; price: number; difference: number;
  differencePercentage: number; isMbga: boolean; color: string; iconName: string;
  updatedAt: string; updatedBy: string; updatedByRole: string | null;
  notes?: string | null; effectiveDate?: string; oldPrice?: number; newPrice?: number;
};
export type AuditEntry = {
  id: string; competitorId: string; competitorName: string; cylinderType: string;
  customerType: string | null; locationPincode: string | null; oldPrice: number;
  newPrice: number; difference: number; isIncrease: boolean; changedBy: string;
  changedByRole: string; timestamp: string; notes: string | null; color: string;
};
export type HistoryPoint = { date: string; [key: string]: string | number };
export type SurveyInput = {
  competitorId: string; cylinderType: string; customerType: string; price: number;
  effectiveDate: string; locationPincode: string; notes?: string;
};
export type BrandInput = { name: string; notes?: string; color: string; depotAddress?: DepotAddress };
export type BenchmarkInput = { cylinderType: string; price: number; notes?: string };
/** Supplying a merchantId selects the Admin API; merchant sessions never send it. */
export function createCompetitorPricingApi(merchantId?: string) {
  if (merchantId !== undefined && !merchantId.trim()) throw new Error("Select a merchant before using admin competitor pricing.");
  const channel = merchantId === undefined ? "merchant" : "admin";
  const root = `/${channel}/competitor-pricing`;
  const scoped = (params: Record<string, unknown> = {}) => ({ ...params, ...(merchantId === undefined ? {} : { merchantId }) });
  return {
  async brands(search: string, signal?: AbortSignal) {
    return (await apiClient.get<Competitor[]>(`${root}/competitors`, { params: scoped({ search: search || undefined }), signal })).data;
  },
  async createBrand(input: BrandInput) {
    return (await apiClient.post<Competitor>(`${root}/competitors`, input, { params: scoped() })).data;
  },
  async status(id: string, status: Competitor["status"]) {
    return (await apiClient.patch<Competitor>(`${root}/competitors/${encodeURIComponent(id)}`, { status }, { params: scoped() })).data;
  },
  async updateDepot(id: string, depotAddress: DepotAddress | null, notes?: string) {
    return (await apiClient.patch<Competitor>(`${root}/competitors/${encodeURIComponent(id)}`, { depotAddress, notes }, { params: scoped() })).data;
  },
  async exportReport(params: ExportOptions) {
    const response = await apiClient.get<Blob>(`${root}/export`, { params: scoped(params), responseType: "blob", timeout: 60000 });
    const match = /filename="([^"]+)"/.exec(String(response.headers["content-disposition"] ?? ""));
    const filename = match?.[1] ?? `competitor-pricing.${params.format.toLowerCase()}`;
    const url = URL.createObjectURL(response.data);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async snapshot(params: MarketFilters, signal?: AbortSignal) {
    return (await apiClient.get<MarketSnapshot>(`${root}/snapshot`, { params: scoped(params), signal })).data;
  },
  async comparison(params: MarketFilters, signal?: AbortSignal) {
    return (await apiClient.get<ComparisonRow[]>(`${root}/comparison`, { params: scoped(params), signal })).data;
  },
  async history(params: MarketFilters & DateRange & { timeframe: Timeframe }, signal?: AbortSignal) {
    return (await apiClient.get<HistoryPoint[]>(`${root}/history`, { params: scoped(params), signal })).data;
  },
  async audit(params: DateRange & { pincode?: string; customerType?: string; cylinderType?: string; competitorId?: string; limit: number; offset: number }, signal?: AbortSignal) {
    return (await apiClient.get<AuditEntry[]>(`${root}/audit-logs`, { params: scoped(params), signal })).data;
  },
  async survey(input: SurveyInput) {
    return (await apiClient.post<{ success: boolean }>(`${root}/prices`, input, { params: scoped() })).data;
  },
  async benchmark(input: BenchmarkInput) {
    return (await apiClient.put<{ success: boolean; mbgaPrice: number }>(`/${channel}/pricing/base-rates`, input, { params: scoped() })).data;
  }
};
}

export const competitorPricingApi = createCompetitorPricingApi();
export type CompetitorPricingApi = ReturnType<typeof createCompetitorPricingApi>;
