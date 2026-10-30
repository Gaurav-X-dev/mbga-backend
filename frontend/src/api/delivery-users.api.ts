import { apiClient } from "./client";
import type {
  DeliveryMember,
  DeliveryMemberCreateInput,
  DeliveryMemberListParams,
  DeliveryMemberListResponse,
  DeliveryMemberStatusAction,
  DeliveryMemberType,
  DeliveryMemberUpdateInput
} from "./delivery-team.api";
import { cleanParams } from "./params";

/**
 * Admin channel: /admin/delivery-users. The same shapes the merchant panel uses for its own
 * team, but scoped by an explicit `merchantId` on every call.
 */
export type AdminDeliveryUser = DeliveryMember;
export type AdminDeliveryUserListParams = DeliveryMemberListParams & { merchantId: string };

const base = "/admin/delivery-users";
const scoped = (merchantId: string) => ({ params: { merchantId } });
const one = (id: string) => `${base}/${encodeURIComponent(id)}`;

export async function listDeliveryUsers(params: AdminDeliveryUserListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliveryMemberListResponse & { items: AdminDeliveryUser[] }>(base, {
    params: cleanParams(params),
    signal
  });
  return data;
}

/** Crew who can be given work right now: of this merchant, active, approved and on duty. */
export async function listAvailableDeliveryUsers(merchantId: string, type: DeliveryMemberType, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliveryMemberListResponse & { items: AdminDeliveryUser[] }>(`${base}/available`, {
    params: { merchantId, delivery_user_type: type, limit: 100 },
    signal
  });
  return data;
}

export async function getDeliveryUser(merchantId: string, id: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<AdminDeliveryUser>(one(id), { ...scoped(merchantId), signal });
  return data;
}

export async function createDeliveryUser(merchantId: string, input: DeliveryMemberCreateInput) {
  const { data } = await apiClient.post<AdminDeliveryUser>(base, input, scoped(merchantId));
  return data;
}

export async function updateDeliveryUser(merchantId: string, id: string, input: DeliveryMemberUpdateInput) {
  const { data } = await apiClient.patch<AdminDeliveryUser>(one(id), input, scoped(merchantId));
  return data;
}

export async function changeDeliveryUserStatus(merchantId: string, id: string, action: DeliveryMemberStatusAction) {
  const { data } = await apiClient.post<AdminDeliveryUser>(`${one(id)}/${action}`, null, scoped(merchantId));
  return data;
}
