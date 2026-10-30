import { apiClient } from "./client";

export type AppSettings = {
  deliveryRadiusMeters: number;
  deliveryRadiusKm: number;
  defaultRadiusMeters?: number;
  overrideRadiusMeters?: number | null;
  merchantId?: string;
  orderCutoffHour?: number;
  orderCutoffLabel?: string;
};
export function settingsPath(merchant: boolean, merchantId?: string) {
  return merchant ? "/merchant/settings" : merchantId ? `/admin/settings/merchants/${encodeURIComponent(merchantId)}` : "/admin/settings";
}
export async function getAppSettings(path: string, signal?: AbortSignal) {
  return (await apiClient.get<AppSettings>(path, { signal })).data;
}
export async function updateAppSettings(path: string, input: { deliveryRadiusMeters?: number | null; orderCutoffHour?: number }) {
  return (await apiClient.patch<AppSettings>(path, input)).data;
}
