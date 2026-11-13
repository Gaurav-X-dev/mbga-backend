import { tokenStorage } from "../auth/token-storage";
import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/reports. `merchantId` is optional here - omit it for all merchants. */
export type ReportType =
  | "VEHICLE_DISPATCH_RETURN"
  | "OUTSTANDING_DUES"
  | "CUSTOMER_COLLECTION"
  | "DAILY_DELIVERY"
  | "PAYMENT_COLLECTION"
  | "PENDING_PICKUP"
  | "EXPENSE"
  | "FUEL"
  | "STOCK_MOVEMENT"
  | "PROFIT_LOSS"
  | "TAX_GST";

export type ExportFormat = "CSV" | "XLSX" | "JSON" | "XML";

export type ReportColumn = { key: string; label: string; align?: "left" | "right" | "center" };

export type Report = {
  type: ReportType;
  title: string;
  period: { from: string; to: string };
  summary: Array<{ label: string; value: string | number }>;
  columns: ReportColumn[];
  rows: Array<Record<string, unknown>>;
  generatedAt: string;
  metadata?: Record<string, unknown>;
};

export type ReportParams = {
  tripVehicle?:string; tripDriver?:string; tripId?:string; tripStatus?:string; tripDateBasis?:string; tripDiscrepanciesOnly?:boolean;
  allTime?: boolean;
  type: ReportType;
  /** ISO date-times. */
  from?: string;
  to?: string;
  merchantId?: string;
  customerId?: string;
  vehicleId?: string;
  driverId?: string;
  fuelType?: string;
  recordedBy?: string;
  destination?: string;
  search?: string;
  hasReceipt?: string;
  telemetry?: string;
  minAmount?: string;
  maxAmount?: string;
  minKmReading?: string;
  maxKmReading?: string;
  minDistance?: string;
  maxDistance?: string;
  minLiters?: string;
  maxLiters?: string;
  minMileage?: string;
  maxMileage?: string;
};

export async function getReport(params: ReportParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<Report>(`/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/reports`, { params: cleanParams(params), signal });
  return data;
}

const EXTENSION: Record<ExportFormat, string> = { CSV: "csv", XLSX: "xlsx", JSON: "json", XML: "xml" };

/** Downloads the export as a file. The server names it when it sends Content-Disposition. */
export async function exportReport(params: ReportParams, format: ExportFormat) {
  const response = await apiClient.get<Blob>(`/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/reports/export`, {
    params: cleanParams({ ...params, format }),
    responseType: "blob",
    timeout: 60_000
  });
  const disposition = String(response.headers["content-disposition"] ?? "");
  const named = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)?.[1];
  const filename = named ? decodeURIComponent(named) : `${params.type.toLowerCase()}-report.${EXTENSION[format]}`;

  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
  return filename;
}
