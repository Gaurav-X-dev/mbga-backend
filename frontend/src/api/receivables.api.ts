import { apiClient } from "./client";
import { cleanParams } from "./params";
import type { ExportFormat, Report } from "./reports.api";

export type ReceivableType = "OUTSTANDING_DUES" | "CUSTOMER_COLLECTION";
export type ReceivableParams = {
  type: ReceivableType;
  merchantId?: string;
  customerId?: string;
  groupId?: string;
  groupBy?: "customer" | "group";
  search?: string;
  customerType?: string;
  city?: string;
  overdueOnly?: boolean;
  minAmount?: number;
  dateFrom?: string;
  dateTo?: string;
  mode?: string;
  status?: string;
  collector?: string;
  sortBy?: "name" | "amount";
  direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
};
export type CustomerReportGroup = { id: string; merchantId: string; name: string; active: boolean };
const BASE = "/admin/reports/receivables";

export async function getReceivables(params: ReceivableParams, signal?: AbortSignal) {
  return (await apiClient.get<Report>(BASE, { params: cleanParams(params), signal })).data;
}
export async function getReceivableDetail(params: ReceivableParams, signal?: AbortSignal) {
  return (await apiClient.get<{ rows: Array<Record<string, unknown>>; total: number }>(`${BASE}/detail`, { params: cleanParams(params), signal })).data;
}
export async function listReportGroups(merchantId?: string, signal?: AbortSignal) {
  return (await apiClient.get<CustomerReportGroup[]>(`${BASE}/groups`, { params: cleanParams({ merchantId }), signal })).data;
}
export async function saveReportGroup(merchantId: string, body: { name: string; active: boolean }, id?: string) {
  return id
    ? (await apiClient.patch<CustomerReportGroup>(`${BASE}/groups/${id}`, body, { params: { merchantId } })).data
    : (await apiClient.post<CustomerReportGroup>(`${BASE}/groups`, body, { params: { merchantId } })).data;
}
export async function assignReportGroup(merchantId: string, customerIds: string[], groupId: string | null) {
  return (await apiClient.put(`${BASE}/groups/assignments`, { customerIds, groupId }, { params: { merchantId } })).data;
}
export async function exportReceivables(params: ReceivableParams, format: ExportFormat) {
  const response = await apiClient.get<Blob>(`${BASE}/export`, {
    params: cleanParams({ ...params, format, offset: 0 }), responseType: "blob", timeout: 60_000
  });
  const named = /filename="([^"]+)"/.exec(String(response.headers["content-disposition"] ?? ""))?.[1];
  const filename = named || `receivables.${format.toLowerCase()}`;
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  return filename;
}
