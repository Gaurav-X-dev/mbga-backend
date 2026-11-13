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
  accountKind?: "OWNER" | "BRANCH" | "STANDALONE";
  ownerCustomerId?: string | null;
  ownerCustomerName?: string | null;
  canCreateBranches?: boolean;
  branchPermissions?: string[] | null;
  priorityCode?: string | null;
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

const channelRoot = () => tokenStorage.get()?.channel === "merchant" ? "/merchant" : "/admin";
const scoped = (merchantId: string) => channelRoot() === "/admin" ? { params: { merchantId } } : {};
const customersRoot = () => `${channelRoot()}/customers`;
const customer = (customerId: string) => `${customersRoot()}/${encodeURIComponent(customerId)}`;

export async function listCustomers(params: CustomerListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<CustomerListResponse>(`/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/customers`, { params: cleanParams(params), signal });
  return data;
}

export async function getCustomer(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Customer>(customer(customerId), { ...scoped(merchantId), signal });
  return data;
}

export async function createCustomer(merchantId: string, input: CustomerCreateInput) {
  const { data } = await apiClient.post<Customer>(customersRoot(), input, scoped(merchantId));
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
    `${channelRoot()}/documents`,
    body,
    { ...scoped(merchantId), timeout: 60_000 }
  );
  return data;
}

import { serverOrigin } from "./openapi.api";

/** A short-lived link to view a document; it expires in minutes, so fetch it on click. */
export async function getDocumentUrl(merchantId: string, fileId: string) {
  const { data } = await apiClient.get<{ url: string; expiresInSeconds: number }>(
    `${channelRoot()}/documents/${encodeURIComponent(fileId)}/url`, scoped(merchantId)
  );
  return data;
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

export async function updateCustomer(merchantId: string, customerId: string, body: { documents?: CustomerCreateInput["documents"]; sites?: CustomerCreateInput["sites"]; customerType?: CustomerType; priorityCode?: string | null; businessName: string; ownerName?: string | null; email?: string | null; deliveryAddress?: Address; reason: string }) {
 const channel = tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin";
 return (await apiClient.patch<Customer>(`/${channel}/customers/${encodeURIComponent(customerId)}`, body, channel === "admin" ? scoped(merchantId) : undefined)).data;
}

export async function deleteCustomer(merchantId: string, customerId: string) {
  const channel = tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin";
  await apiClient.delete(`/${channel}/customers/${encodeURIComponent(customerId)}`, scoped(merchantId));
}

export async function createCustomerBranch(merchantId: string, ownerId: string, input: CustomerCreateInput) {
  return (await apiClient.post<Customer>(`${channelRoot()}/customer-access/customers/${encodeURIComponent(ownerId)}/branches`, input, scoped(merchantId))).data;
}

export const CUSTOMER_PERMISSION_LABELS: Record<string, string> = {
  "profile.view": "View profile",
  "orders.view": "View orders",
  "orders.create": "Place orders",
  "orders.cancel": "Cancel orders",
  "accounts.view": "View invoices, balance and advances",
  "accounts.pay": "Make payments and request advance deposits",
  "inventory.view": "View inventory and movements",
  "notifications.view": "View notifications and mark read"
};
export const BRANCH_PERMISSIONS = ["profile.view", "orders.view", "orders.create", "orders.cancel", "accounts.view", "accounts.pay", "inventory.view", "notifications.view"] as const;
export async function updateCustomerBranch(merchantId: string, ownerId: string, branchId: string, body: unknown) {
  return (await apiClient.patch<Customer>(`${channelRoot()}/customer-access/customers/${encodeURIComponent(ownerId)}/branches/${encodeURIComponent(branchId)}`, body, scoped(merchantId))).data;
}
export async function deleteCustomerBranch(merchantId: string, ownerId: string, branchId: string) {
  await apiClient.delete(`${channelRoot()}/customer-access/customers/${encodeURIComponent(ownerId)}/branches/${encodeURIComponent(branchId)}`, scoped(merchantId));
}

export type CustomerKycRequirements = {
  customerType: string; minimumDocuments: number; requiresDeliverySites: boolean;
  documents: Array<{type: string; label: string; required: boolean; requiredGroup?: string | null; numberFormat: string}>;
};
export async function getCustomerKycRequirements(customerType: string, signal?: AbortSignal) {
  return (await apiClient.get<CustomerKycRequirements>("/customer/registration/kyc-requirements", {params:{customerType}, signal})).data;
}
