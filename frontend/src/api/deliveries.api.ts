import { apiClient } from "./client";
import { cleanParams } from "./params";
import type { Address } from "./orders.api";

/** Admin channel: /admin/deliveries. Merchant-scoped - `merchantId` on every call. */
export type DeliveryStatus = "SCHEDULED" | "DISPATCHED" | "ON_LOCATION" | "DELIVERED" | "FAILED";

export type DeliverySlip = {
  id: string;
  slipNumber: string;
  orderId: string;
  orderNumber: string;
  customerId: string;
  customerName: string;
  deliveryAddress: Address;
  deliverySiteName: string;
  items: Array<{ cylinderType: string; cylinderLabel: string; quantity: number }>;
  itemsSummary: string;
  cylindersAllocated: number;
  vehicleNumber: string;
  driverName: string;
  helperName?: string | null;
  scheduledDate: string;
  dispatchedAt?: string | null;
  deliveredAt?: string | null;
  subtotal: number;
  gstPercent: number;
  gstAmount: number;
  totalAmount: number;
  emptiesCollected: number;
  pendingPickup: number;
  confirmationMethod: "OTP" | "SIGNATURE" | "PHOTO" | "NONE";
  status: DeliveryStatus;
  failureReason?: string | null;
  note?: string | null;
  devConfirmationCode?: string | null;
};

export type DeliveryListParams = {
  merchantId: string;
  /** A DeliveryStatus or `ALL`. */
  status?: string;
  search?: string;
};

/** Only what is sent changes. */
export type ReassignDeliveryInput = {
  vehicleNumber?: string;
  driverName?: string;
  helperName?: string;
  deliveryDate?: string;
  reason?: string;
};

export async function listDeliveries(params: DeliveryListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliverySlip[]>("/admin/deliveries", { params: cleanParams(params), signal });
  return data;
}

export async function getDelivery(merchantId: string, deliveryId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<DeliverySlip>(`/admin/deliveries/${encodeURIComponent(deliveryId)}`, {
    params: { merchantId },
    signal
  });
  return data;
}

export async function reassignDelivery(merchantId: string, deliveryId: string, input: ReassignDeliveryInput) {
  const { data } = await apiClient.patch<DeliverySlip>(
    `/admin/deliveries/${encodeURIComponent(deliveryId)}/assignment`,
    input,
    { params: { merchantId } }
  );
  return data;
}
