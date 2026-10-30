import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/kyc/applications (read-only; merchants own the decision) */
export type KycApplicationSummary = {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_mobile: string | null;
  customer_type: string | null;
  city: string | null;
  merchant_id: string | null;
  merchant_name: string | null;
  status: string;
  submitted_at: string;
  reviewed_at: string | null;
  reviewed_by_name: string | null;
  rejection_reason: string | null;
  document_count: number;
  verified_document_count: number;
};

export type KycApplicationListResponse = {
  items: KycApplicationSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type KycStats = {
  pending: number;
  approved: number;
  rejected: number;
  total: number;
};

export type KycDocumentFile = {
  fileId: string;
  fileName: string;
  fileSize?: number;
  side?: "FRONT" | "BACK" | "PAGE_1" | "PAGE_2" | string;
  source?: "CAMERA" | "GALLERY" | "FILE_PICKER" | string;
  uploadedAt?: string;
};

export type KycDocument = {
  id?: string;
  type: string;
  /** Masked by default; full numbers use the separate permission-checked reveal endpoint. */
  numberMasked: string;
  fileName?: string | null;
  /** Exchanged for a short-lived link via /admin/documents/{fileId}/url. */
  fileId?: string | null;
  files?: KycDocumentFile[];
  fileIds?: string[];
  uploadedAt?: string | null;
  status: "UPLOADED" | "VERIFIED" | "REJECTED" | string;
};

export type KycAddress = {
  line1?: string | null;
  line2?: string | null;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
};

/** GET /admin/kyc/applications/{id} - the spec's KycApplicationResponse (camelCase). */
export type KycApplicationDetail = {
  id: string;
  customerId: string;
  customerType?: string | null;
  businessName?: string | null;
  ownerName?: string | null;
  mobile: string;
  email?: string | null;
  documents?: KycDocument[];
  deliveryAddress: KycAddress;
  sites?: Array<{
    id: string;
    name: string;
    address: KycAddress;
    contactName?: string | null;
    contactMobile?: string | null;
    isPrimary: boolean;
  }>;
  status: string;
  submittedAt: string;
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  rejectionReason?: string | null;
};

export type KycListParams = {
  status?: string;
  merchantId?: string;
  search?: string;
  limit: number;
  offset: number;
};

export async function listKycApplications(params: KycListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<KycApplicationListResponse>("/admin/kyc/applications", {
    params: cleanParams(params),
    signal
  });
  return data;
}

export async function getKycStats(signal?: AbortSignal) {
  const { data } = await apiClient.get<KycStats>("/admin/kyc/applications/stats", { signal });
  return data;
}

export async function getKycApplication(applicationId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<KycApplicationDetail>(
    `/admin/kyc/applications/${encodeURIComponent(applicationId)}`,
    { signal }
  );
  return data;
}

// ---------------------------------------------------------------------------
// V2 Endpoints (Channel: Merchant & Customer V2)
// Live Backend: https://mbga.clocktales.com
// ---------------------------------------------------------------------------

export type KycDocumentFileResponseV2 = {
  fileId: string;
  fileName: string;
  fileSize: number;
  contentType: string;
  side: "FRONT" | "BACK" | "PAGE_1" | "PAGE_2" | string;
  source: "CAMERA" | "GALLERY" | "FILE_PICKER" | string;
  sortOrder: number;
};

export type KycDocumentResponseV2 = {
  id: string;
  type: string;
  numberMasked: string;
  status: string;
  files: KycDocumentFileResponseV2[];
};

export type MerchantKycApplicationResponseV2 = {
  id: string;
  customerId: string;
  customerType?: string | null;
  businessName?: string | null;
  ownerName?: string | null;
  mobile: string;
  email?: string | null;
  documents: KycDocumentResponseV2[];
  deliveryAddress: KycAddress;
  sites?: Array<{
    id: string;
    name: string;
    address: KycAddress;
    contactName?: string | null;
    contactMobile?: string | null;
    isPrimary: boolean;
  }>;
  status: string;
  submittedAt: string;
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  rejectionReason?: string | null;
};

export type MerchantKycApplicationListResponseV2 = {
  items: MerchantKycApplicationResponseV2[];
  total: number;
  limit: number;
  offset: number;
};

export type KycDocumentRequirementV2 = {
  type: string;
  label: string;
  required: boolean;
  requiredGroup?: string | null;
  numberFormat: string;
  minFiles?: number;
  maxFiles?: number;
  allowedSides: string[];
  allowedMimeTypes: string[];
  maxSizeBytes: number;
};

export type KycRequirementsResponseV2 = {
  customerType: string;
  minimumDocuments: number;
  documents: KycDocumentRequirementV2[];
};

import { serverOrigin } from "./openapi.api";

function v2Url(path: string): string {
  try {
    const origin = serverOrigin();
    return origin ? `${origin.replace(/\/+$/, "")}${path}` : path;
  } catch {
    return path;
  }
}

/** GET /api/v2/merchant/kyc/applications */
export async function listKycApplicationsV2(
  params?: { status?: string; limit?: number; offset?: number },
  signal?: AbortSignal
) {
  const { data } = await apiClient.get<MerchantKycApplicationListResponseV2>(
    v2Url("/api/v2/merchant/kyc/applications"),
    { params: cleanParams(params ?? {}), signal }
  );
  return data;
}

/** GET /api/v2/merchant/kyc/applications/{application_id} */
export async function getKycApplicationV2(applicationId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<MerchantKycApplicationResponseV2>(
    v2Url(`/api/v2/merchant/kyc/applications/${encodeURIComponent(applicationId)}`),
    { signal }
  );
  return data;
}

/** POST /api/v2/merchant/kyc/applications/{application_id}/approve */
export async function approveKycApplicationV2(applicationId: string, signal?: AbortSignal) {
  const { data } = await apiClient.post<MerchantKycApplicationResponseV2>(
    v2Url(`/api/v2/merchant/kyc/applications/${encodeURIComponent(applicationId)}/approve`),
    {},
    { signal }
  );
  return data;
}

/** POST /api/v2/merchant/kyc/applications/{application_id}/reject */
export async function rejectKycApplicationV2(
  applicationId: string,
  body: { reason: string; notes?: string },
  signal?: AbortSignal
) {
  const { data } = await apiClient.post<MerchantKycApplicationResponseV2>(
    v2Url(`/api/v2/merchant/kyc/applications/${encodeURIComponent(applicationId)}/reject`),
    body,
    { signal }
  );
  return data;
}

/** GET /api/v2/merchant/documents/{file_id}/url */
export async function getMerchantDocumentUrlV2(fileId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<{ url: string; expiresInSeconds?: number }>(
    v2Url(`/api/v2/merchant/documents/${encodeURIComponent(fileId)}/url`),
    { signal }
  );
  return data;
}

/** Returns the URL for GET /api/v2/merchant/documents/{file_id}/content?token=... */
export function getMerchantDocumentContentUrlV2(fileId: string, token: string, baseUrl = ""): string {
  const prefix = baseUrl ? baseUrl.replace(/\/+$/, "") : serverOrigin();
  return `${prefix}/api/v2/merchant/documents/${encodeURIComponent(fileId)}/content?token=${encodeURIComponent(token)}`;
}

/** GET /api/v2/customer/registration/kyc-requirements */
export async function getKycRequirementsV2(customerType: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<KycRequirementsResponseV2>(
    v2Url("/api/v2/customer/registration/kyc-requirements"),
    { params: { customerType }, signal }
  );
  return data;
}

/** Full identifiers are fetched on demand through the audited, permission-checked route. */
export async function revealDocumentNumber(applicationId: string, documentId: string) {
  const {data} = await apiClient.get<{documentId: string; documentType: string; number: string; numberMasked: string}>(
    `/admin/kyc/applications/${encodeURIComponent(applicationId)}/documents/${encodeURIComponent(documentId)}/number`
  );
  return data;
}
