import { apiClient } from "./client";
import { tokenStorage } from "../auth/token-storage";
import { cleanParams } from "./params";
import type { Address } from "./orders.api";

/** Admin channel: /admin/customers (merchant-scoped - `merchantId` on every call). */
export type CustomerType = "RETAIL" | "INDUSTRIAL";
export type KycDocumentType = "AADHAAR" | "PAN" | "FSSAI" | "GST" | "MSME";

export type CustomerDocument = {
  id?: string;
  files?: Array<{fileId: string; fileName: string; side: string; fileSize?: number; contentType?: string; sortOrder?: number}>;
  type: string;
  /** The only form of the identifier that ever leaves the backend. */
  numberMasked: string;
  fileName: string;
  fileId?: string | null;
  uploadedAt: string;
  status: "UPLOADED" | "VERIFIED" | "REJECTED";
};

export type DeliverySite = {
  id: string;
  name: string;
  address: Address;
  contactName?: string | null;
  contactMobile?: string | null;
  isPrimary: boolean;
};

export type Customer = {
  id: string;
  code?: string | null;
  customerType?: CustomerType | string | null;
  businessName?: string | null;
  ownerName?: string | null;
  mobile: string;
  email?: string | null;
  accountStatus: string;
  kycStatus: string;
  pricingTier: string;
  deliveryAddress: Address;
  sites?: DeliverySite[];
  documents?: CustomerDocument[];
  gstin?: string | null;
  employeeId?: string | null;
  employeeName?: string | null;
  registeredAt?: string | null;
  approvedAt?: string | null;
  rejectionReason?: string | null;
  runningBalance: number;
  lastOrderAt?: string | null;
  applicationId?: string | null;
};

export type CustomerListResponse = { items: Customer[]; total: number; limit: number; offset: number };

export type CustomerListParams = {
  employee?: string;
  dateFrom?: string;
  dateTo?: string;
  merchantId: string;
  search?: string;
  /** RETAIL, INDUSTRIAL or ALL. */
  customerType?: string;
  /** An account status or ALL. */
  accountStatus?: string;
  gstStatus?: "ALL" | "GST" | "NON_GST";
  limit: number;
  offset: number;
};

export type CustomerCreateInput = {
  customerType: CustomerType;
  businessName: string;
  ownerName: string;
  mobile: string;
  email?: string;
  deliveryAddress: Address;
  documents: Array<{ type: KycDocumentType; number: string; fileId?: string }>;
  sites: Array<{ name: string; address: Address; contactName?: string; contactMobile?: string; isPrimary?: boolean }>;
};

export type Eligibility = { eligible: boolean; reasons?: string[] };

export type CustomerPriceItem = {
  cylinderType: string;
  cylinderLabel: string;
  tierPrice: number | null;
  override?: { overridePrice: number; effectiveFrom: string; reason?: string | null; setBy: string; setAt: string } | null;
  effectivePrice: number | null;
};

export type CustomerPricing = { customerId: string; tier: string; items?: CustomerPriceItem[] };

export type CustomerPaymentSummary = {
  totalInvoiced: number;
  totalPaid: number;
  runningBalance: number;
  overdueAmount: number;
  lastPaymentAt?: string | null;
};

const scoped = (merchantId: string) => ({ params: { merchantId } });
const customer = (customerId: string) => `/admin/customers/${encodeURIComponent(customerId)}`;

export async function listCustomers(params: CustomerListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<CustomerListResponse>(`/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/customers`, { params: cleanParams(params), signal });
  return data;
}

export async function getCustomer(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Customer>(customer(customerId), { ...scoped(merchantId), signal });
  return data;
}

export async function createCustomer(merchantId: string, input: CustomerCreateInput) {
  const { data } = await apiClient.post<Customer>("/admin/customers", input, scoped(merchantId));
  return data;
}

export async function getCustomerEligibility(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Eligibility>(`${customer(customerId)}/eligibility`, { ...scoped(merchantId), signal });
  return data;
}

export async function approveCustomer(merchantId: string, customerId: string) {
  const { data } = await apiClient.post(`${customer(customerId)}/approve`, null, scoped(merchantId));
  return data;
}

export async function rejectCustomer(merchantId: string, customerId: string, reason: string) {
  const { data } = await apiClient.post(`${customer(customerId)}/reject`, { reason }, scoped(merchantId));
  return data;
}

export async function getCustomerPricing(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<CustomerPricing>(`${customer(customerId)}/pricing`, { ...scoped(merchantId), signal });
  return data;
}

export async function setCustomerPrice(
  merchantId: string,
  customerId: string,
  cylinderType: string,
  input: { overridePrice: number; effectiveFrom?: string; reason?: string }
) {
  const { data } = await apiClient.put<CustomerPriceItem>(
    `${customer(customerId)}/pricing/${encodeURIComponent(cylinderType)}`,
    input,
    scoped(merchantId)
  );
  return data;
}

export async function removeCustomerPrice(merchantId: string, customerId: string, cylinderType: string) {
  const { data } = await apiClient.delete<CustomerPriceItem>(
    `${customer(customerId)}/pricing/${encodeURIComponent(cylinderType)}`,
    scoped(merchantId)
  );
  return data;
}

export async function getCustomerPaymentSummary(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<CustomerPaymentSummary>(`${customer(customerId)}/payments/summary`, {
    ...scoped(merchantId),
    signal
  });
  return data;
}

/** Uploads a KYC file and returns its `fileId` for the registration body. */
export async function uploadDocument(merchantId: string, file: File, type: KycDocumentType) {
  const body = new FormData();
  body.append("file", file);
  body.append("type", type);
  const { data } = await apiClient.post<{ fileId: string; fileName: string; contentType: string; size: number }>(
    "/admin/documents",
    body,
    { ...scoped(merchantId), timeout: 60_000 }
  );
  return data;
}

import { serverOrigin } from "./openapi.api";

/** A short-lived link to view a document; it expires in minutes, so fetch it on click. */
export async function getDocumentUrl(merchantId: string, fileId: string) {
  try {
    const origin = serverOrigin();
    const url = origin ? `${origin.replace(/\/+$/, "")}/api/v2/merchant/documents/${encodeURIComponent(fileId)}/url` : `/api/v2/merchant/documents/${encodeURIComponent(fileId)}/url`;
    const { data } = await apiClient.get<{ url: string; expiresInSeconds: number }>(url, scoped(merchantId));
    return data;
  } catch {
    const { data } = await apiClient.get<{ url: string; expiresInSeconds: number }>(
      `/admin/documents/${encodeURIComponent(fileId)}/url`,
      scoped(merchantId)
    );
    return data;
  }
}

/** URL builder for GET /api/v2/merchant/documents/{file_id}/content?token=... */
export function getDocumentContentUrl(fileId: string, token: string, baseUrl = ""): string {
  const prefix = baseUrl ? baseUrl.replace(/\/+$/, "") : serverOrigin();
  return `${prefix}/api/v2/merchant/documents/${encodeURIComponent(fileId)}/content?token=${encodeURIComponent(token)}`;
}

export async function listCustomerEmployees(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Array<{ value: string; label: string }>>(`/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/customers/employees`, {
    params: { merchantId }, signal
  });
  return data;
}
