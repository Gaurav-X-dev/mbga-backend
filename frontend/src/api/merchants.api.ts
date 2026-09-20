import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/merchants */
export type Merchant = {
  id: string;
  merchant_code: string;
  business_name: string;
  contact_person_name: string | null;
  mobile_number: string | null;
  email: string | null;
  gst_number: string | null;
  address_line_1: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  primary_user_id: string | null;
  status: string;
  approval_status: string;
  role: string;
  allowed_channel: string;
  created_at: string;
};

export type MerchantListResponse = {
  items: Merchant[];
  total: number;
  limit: number;
  offset: number;
};

export type MerchantListParams = {
  search?: string;
  status?: string;
  city?: string;
  state?: string;
  limit: number;
  offset: number;
};

export type MerchantCreateInput = {
  merchant_code: string;
  business_name: string;
  contact_person_name: string;
  mobile_number: string;
  email?: string;
  gst_number?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
};

export type MerchantUpdateInput = {
  business_name?: string;
  contact_person_name?: string;
  email?: string | null;
  gst_number?: string | null;
  address_line_1?: string | null;
  address_line_2?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
};

export type MerchantUser = {
  id: string;
  merchant_id: string;
  user_id: string;
  full_name: string | null;
  mobile_number: string | null;
  email: string | null;
  staff_type: string | null;
  status: string;
  created_at: string;
};

export type MerchantUserCreateInput = {
  full_name: string;
  mobile_number: string;
  email?: string;
  staff_type: string;
};

export type MerchantUserUpdateInput = {
  full_name?: string;
  email?: string | null;
  staff_type?: string;
  status?: string;
};

export async function listMerchants(params: MerchantListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<MerchantListResponse>("/admin/merchants", { params: cleanParams(params), signal });
  return data;
}

export async function getMerchant(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Merchant>(`/admin/merchants/${encodeURIComponent(merchantId)}`, { signal });
  return data;
}

export async function createMerchant(input: MerchantCreateInput) {
  const { data } = await apiClient.post<Merchant>("/admin/merchants", input);
  return data;
}

export async function updateMerchant(merchantId: string, input: MerchantUpdateInput) {
  const { data } = await apiClient.patch<Merchant>(`/admin/merchants/${encodeURIComponent(merchantId)}`, input);
  return data;
}

export type MerchantStatusAction = "activate" | "block" | "unblock";

export async function changeMerchantStatus(merchantId: string, action: MerchantStatusAction) {
  const { data } = await apiClient.post<Merchant>(`/admin/merchants/${encodeURIComponent(merchantId)}/${action}`);
  return data;
}

export async function listMerchantUsers(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<MerchantUser[]>(`/admin/merchants/${encodeURIComponent(merchantId)}/users`, {
    signal
  });
  return data;
}

export async function createMerchantUser(merchantId: string, input: MerchantUserCreateInput) {
  const { data } = await apiClient.post<MerchantUser>(
    `/admin/merchants/${encodeURIComponent(merchantId)}/users`,
    input
  );
  return data;
}

export async function updateMerchantUser(merchantId: string, userId: string, input: MerchantUserUpdateInput) {
  const { data } = await apiClient.patch<MerchantUser>(
    `/admin/merchants/${encodeURIComponent(merchantId)}/users/${encodeURIComponent(userId)}`,
    input
  );
  return data;
}
