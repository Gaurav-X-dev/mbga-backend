import { tokenStorage } from "../auth/token-storage";
import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/inventory. Merchant-scoped like orders - `merchantId` on every call. */
export type StockBucket = "filled" | "empty" | "damaged";

export type StockMovementType =
  | "RECEIVED_FILLED"
  | "SENT_TO_PLANT"
  | "MARKED_DAMAGED"
  | "CORRECTION"
  | "DISPATCHED"
  | "EMPTIES_COLLECTED";

/** DISPATCHED and EMPTIES_COLLECTED are written by the delivery flow and refused here. */
export type RecordableMovementType = Extract<StockMovementType, "RECEIVED_FILLED" | "SENT_TO_PLANT" | "MARKED_DAMAGED" | "CORRECTION">;

export type StockItem = {
  cylinderType: string;
  cylinderLabel: string;
  filled: number;
  empty: number;
  damaged: number;
  reorderThreshold: number;
  updatedAt?: string | null;
};

export type StockAlert = {
  id: string;
  cylinderType: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  message: string;
};

export type InventorySnapshot = {
  items: StockItem[];
  alerts: StockAlert[];
  asOf: string;
};

export type StockMovement = {
  id: string;
  type: StockMovementType;
  cylinderType: string;
  cylinderLabel: string;
  quantity: number;
  deltas: Partial<Record<StockBucket, number>>;
  note?: string | null;
  referenceType?: "ORDER" | "DELIVERY" | "CHALLAN" | null;
  referenceId?: string | null;
  recordedBy?: string | null;
  recordedAt: string;
};

export type MovementListParams = {
  merchantId: string;
  /** A cylinder type code, or `ALL`. */
  cylinderType?: string;
  limit?: number;
};

export type RecordMovementInput = {
  type: RecordableMovementType;
  cylinderType: string;
  quantity?: number;
  fromBucket?: StockBucket;
  bucket?: StockBucket;
  newCount?: number;
  note?: string;
  referenceId?: string;
};

const base = () => `/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/inventory`;

export async function getInventory(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<InventorySnapshot>(base(), { params: { merchantId }, signal });
  return data;
}

export async function listStockMovements(params: MovementListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<StockMovement[]>(`${base()}/movements`, {
    params: cleanParams(params),
    signal
  });
  return data;
}

/** `idempotencyKey` makes a double-click or a retry book the movement once. */
export async function recordStockMovement(merchantId: string, input: RecordMovementInput, idempotencyKey: string) {
  const { data } = await apiClient.post<StockMovement>(`${base()}/movements`, input, {
    params: { merchantId },
    headers: { "Idempotency-Key": idempotencyKey }
  });
  return data;
}

export async function updateReorderThreshold(merchantId: string, cylinderType: string, reorderThreshold: number) {
  const {data} = await apiClient.patch<StockItem>(`${base()}/${encodeURIComponent(cylinderType)}/reorder-threshold`,
    {reorderThreshold},{params:{merchantId}});
  return data;
}
