import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Merchant channel: /merchant/delivery-users (always scoped to the signed-in merchant by the backend) */
export type DeliveryMemberType = "DRIVER" | "HELPER";

export type DeliveryMember = {
  id: string;
  merchant_id: string;
  user_id: string;
  delivery_user_type: DeliveryMemberType | string;
  full_name: string | null;
  mobile_number: string | null;
  email: string | null;
  employee_code: string | null;
  driving_license_number: string | null;
  driving_license_expiry: string | null;
  address: string | null;
  status: string;
  approval_status: string;
  role: string;
  allowed_channel: string;
  created_at: string;
};

export type DeliveryMemberListResponse = {
  items: DeliveryMember[];
  total: number;
  limit: number;
  offset: number;
};

export type DeliveryMemberListParams = {
  search?: string;
  delivery_user_type?: string;
  status?: string;
  limit: number;
  offset: number;
};

export type DeliveryMemberCreateInput = {
  delivery_user_type: DeliveryMemberType;
  full_name: string;
  mobile_number: string;
  email?: string;
  employee_code: string;
  driving_license_number?: string;
  /** yyyy-mm-dd */
  driving_license_expiry?: string;
  address?: string;
};

export type DeliveryMemberUpdateInput = {
  full_name?: string;
  email?: string | null;
  employee_code?: string;
  driving_license_number?: string | null;
  driving_license_expiry?: string | null;
  address?: string | null;
};

const base = "/merchant/delivery-users";

export async function listDeliveryMembers(params: DeliveryMemberListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliveryMemberListResponse>(base, { params: cleanParams(params), signal });
  return data;
}

export async function getDeliveryMember(memberId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliveryMember>(`${base}/${encodeURIComponent(memberId)}`, { signal });
  return data;
}

export async function createDeliveryMember(input: DeliveryMemberCreateInput) {
  const { data } = await apiClient.post<DeliveryMember>(base, input);
  return data;
}

export async function updateDeliveryMember(memberId: string, input: DeliveryMemberUpdateInput) {
  const { data } = await apiClient.patch<DeliveryMember>(`${base}/${encodeURIComponent(memberId)}`, input);
  return data;
}

export type DeliveryMemberStatusAction = "activate" | "block" | "unblock";

export async function changeDeliveryMemberStatus(memberId: string, action: DeliveryMemberStatusAction) {
  const { data } = await apiClient.post<DeliveryMember>(`${base}/${encodeURIComponent(memberId)}/${action}`);
  return data;
}
