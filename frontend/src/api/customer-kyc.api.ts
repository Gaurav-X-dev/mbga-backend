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

export type KycDocument = {
  id: string;
  document_type?: string | null;
  status?: string | null;
  file_name?: string | null;
  uploaded_at?: string | null;
  [key: string]: unknown;
};

/**
 * The detail response is the merchant reviewer's shape, reused as-is. Its nested customer
 * and document objects are typed loosely here because the panel only reads a few fields and
 * the backend owns the full contract.
 */
export type KycApplicationDetail = {
  id: string;
  status: string;
  submitted_at: string;
  reviewed_at?: string | null;
  reviewed_by_name?: string | null;
  rejection_reason?: string | null;
  customer?: Record<string, unknown> | null;
  documents?: KycDocument[] | null;
  delivery_sites?: Array<Record<string, unknown>> | null;
  [key: string]: unknown;
};

export type KycListParams = {
  status?: string;
  merchant_id?: string;
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
