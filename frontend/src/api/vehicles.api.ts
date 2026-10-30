import { apiClient } from "./client";
import { cleanParams } from "./params";

/**
 * Admin channel: /admin/vehicles. Merchant-scoped - `merchantId` on every call.
 * A van is never deleted; `isActive: false` retires it, because old slips still name it.
 */
export type Vehicle = {
  id: string;
  number: string;
  label?: string | null;
  notes?: string | null;
  isActive: boolean;
  createdAt: string;
};

export type VehicleListResponse = { items: Vehicle[]; total: number };

export type VehicleListParams = { merchantId: string; activeOnly?: boolean; search?: string };

export type VehicleInput = { number?: string; label?: string | null; notes?: string | null; isActive?: boolean };

const base = "/admin/vehicles";
const scoped = (merchantId: string) => ({ params: { merchantId } });

export async function listVehicles(params: VehicleListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<VehicleListResponse>(base, { params: cleanParams(params), signal });
  return data;
}

/** Vans that may be assigned today - what an assignment dropdown should offer. */
export async function listAvailableVehicles(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<VehicleListResponse>(`${base}/available`, { ...scoped(merchantId), signal });
  return data;
}

export async function createVehicle(merchantId: string, input: { number: string; label?: string; notes?: string }) {
  const { data } = await apiClient.post<Vehicle>(base, input, scoped(merchantId));
  return data;
}

export async function updateVehicle(merchantId: string, vehicleId: string, input: VehicleInput) {
  const { data } = await apiClient.patch<Vehicle>(`${base}/${encodeURIComponent(vehicleId)}`, input, scoped(merchantId));
  return data;
}

/** A van as an assignment dropdown offers it: eligible for this order or slip, by pincode. */
export type EligibleVehicle = Vehicle & {
  busyWithDriverName?: string | null;
  busyWithDriverUserId?: string | null;
  /** Lower comes first. */
  priority?: number | null;
  /** The pincode that made this van eligible, when one did. */
  matchedPincode?: string | null;
};

export type VehiclePincodes = { vehicleId: string; pincodes: string[] };

export async function getVehiclePincodes(merchantId: string, vehicleId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<VehiclePincodes>(`${base}/${encodeURIComponent(vehicleId)}/pincodes`, { ...scoped(merchantId), signal });
  return data;
}

/** Replaces the whole mapping, so always send the complete list. */
export async function setVehiclePincodes(merchantId: string, vehicleId: string, pincodes: string[]) {
  const { data } = await apiClient.put<VehiclePincodes>(`${base}/${encodeURIComponent(vehicleId)}/pincodes`, { pincodes }, scoped(merchantId));
  return data;
}

/** Vans eligible to take this order, for the confirm dialog. */
export async function listOrderEligibleVehicles(merchantId: string, orderId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<EligibleVehicle[]>(`/admin/orders/${encodeURIComponent(orderId)}/available-vehicles`, { ...scoped(merchantId), signal });
  return data;
}

/** Vans eligible to take over this slip, for reassignment. */
export async function listDeliveryEligibleVehicles(merchantId: string, deliveryId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<EligibleVehicle[]>(`/admin/deliveries/${encodeURIComponent(deliveryId)}/available-vehicles`, {
    ...scoped(merchantId),
    signal
  });
  return data;
}
