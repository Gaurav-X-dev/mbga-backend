import { apiClient } from "./client";
import { cleanParams } from "./params";

/**
 * Admin channel: /admin/orders. Every call is merchant-scoped — the backend requires
 * `merchantId` on each request, so the panel always works inside one selected merchant.
 */
export type OrderStatus = "PLACED" | "CONFIRMED" | "OUT_FOR_DELIVERY" | "ON_LOCATION" | "DELIVERED" | "CANCELLED";

export type Address = {
  line1?: string;
  line2?: string | null;
  city?: string;
  state?: string;
  pincode?: string;
  latitude?: number | null;
  longitude?: number | null;
  formattedAddress?: string | null;
  placeId?: string | null;
  floorUnit?: string | null;
  landmark?: string | null;
  deliveryInstructions?: string | null;
  postOffice?: string | null;
};

export type OrderItem = {
  cylinderType: string;
  cylinderLabel: string;
  quantity: number;
  /** GST-inclusive, per cylinder. */
  unitPrice: number;
  lineTotal: number;
};

export type OrderStatusEntry = {
  status: string;
  label: string;
  at: string;
  by?: string | null;
  note?: string | null;
};

export type Cutoff = {
  cutoffTime: string;
  withinCutoff: boolean;
  scheduledDeliveryDate: string;
  message: string;
};

export type Order = {
  id: string;
  orderNumber: string;
  customerId: string;
  customerName: string;
  customerType: string;
  items?: OrderItem[];
  totalCylinders: number;
  itemsSummary: string;
  orderMode: "NEW" | "REPEAT";
  source: "CUSTOMER_APP" | "MERCHANT_APP";
  deliverySiteId?: string | null;
  deliverySiteName: string;
  deliveryAddress: Address;
  subtotal: number;
  gstPercent: number;
  gstAmount: number;
  totalAmount: number;
  status: OrderStatus;
  canCancel: boolean;
  statusHistory?: OrderStatusEntry[];
  placedAt: string;
  cutoff: Cutoff;
  createdBy?: string | null;
  deliverySlipId?: string | null;
  deliveryOtp?: string | null;
  invoiceId?: string | null;
};

export type OrderStatusMeta = {
  code: OrderStatus;
  label: string;
  sequence: number;
  tone: "success" | "warning" | "error" | "info" | "pending" | "neutral";
  description: string;
  isTerminal: boolean;
};

export type DeliveryAssignment = {
  vehicleNumber: string;
  vehicle_number?: string | null;
  driverUserId?: string | null;
  driver_user_id?: string | null;
  deliveryUserId?: string | null;
  delivery_user_id?: string | null;
  driverId?: string | null;
  driver_id?: string | null;
  driverName?: string | null;
  driver_name?: string | null;
  helperUserId?: string | null;
  helper_user_id?: string | null;
  helperId?: string | null;
  helper_id?: string | null;
  helperName?: string | null;
  helper_name?: string | null;
  deliveryDate?: string | null;
  delivery_date?: string | null;
};

export type OrderListParams = {
  merchantId: string;
  /** A status code, `ALL`, or `ACTIVE` for every non-terminal status. */
  status?: string;
  search?: string;
  customerId?: string;
};

export async function listOrders(params: OrderListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<Order[]>("/admin/orders", { params: cleanParams(params), signal });
  return data;
}

export async function getOrder(merchantId: string, orderId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Order>(`/admin/orders/${encodeURIComponent(orderId)}`, {
    params: { merchantId },
    signal
  });
  return data;
}

export async function listOrderStatuses(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<OrderStatusMeta[]>("/admin/orders/statuses", { params: { merchantId }, signal });
  return data;
}

export async function getOrderCutoff(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Cutoff>("/admin/orders/cutoff", { params: { merchantId }, signal });
  return data;
}

function normalizeDeliveryPayload(delivery: DeliveryAssignment): Record<string, any> {
  const driverId =
    delivery.driverUserId ||
    delivery.driver_user_id ||
    delivery.driverId ||
    delivery.driver_id;
  const deliveryMemberId =
    delivery.deliveryUserId ||
    delivery.delivery_user_id ||
    driverId;
  const driverName = delivery.driverName || delivery.driver_name;
  const vNum = (delivery.vehicleNumber || delivery.vehicle_number || "").trim().toUpperCase();
  const dDate = delivery.deliveryDate || delivery.delivery_date;
  const helperId =
    delivery.helperUserId ||
    delivery.helper_user_id ||
    delivery.helperId ||
    delivery.helper_id;
  const helperName = delivery.helperName || delivery.helper_name;

  return {
    vehicleNumber: vNum,
    vehicle_number: vNum,
    ...(dDate ? { deliveryDate: dDate, delivery_date: dDate } : {}),
    ...(driverId
      ? {
          driverUserId: driverId,
          driver_user_id: driverId,
          driver_id: driverId,
          driverId: driverId,
        }
      : {}),
    ...(deliveryMemberId
      ? {
          deliveryUserId: deliveryMemberId,
          delivery_user_id: deliveryMemberId,
        }
      : {}),
    ...(driverName
      ? {
          driverName,
          driver_name: driverName,
        }
      : {}),
    ...(helperId
      ? {
          helperUserId: helperId,
          helper_user_id: helperId,
          helper_id: helperId,
          helperId: helperId,
        }
      : {}),
    ...(helperName
      ? {
          helperName,
          helper_name: helperName,
        }
      : {}),
  };
}

export async function confirmOrder(merchantId: string, orderId: string, delivery: DeliveryAssignment) {
  const deliveryPayload = normalizeDeliveryPayload(delivery);
  const req = {
    delivery: deliveryPayload,
    ...deliveryPayload,
  };
  const { data } = await apiClient.post<Order>(
    `/admin/orders/${encodeURIComponent(orderId)}/confirm`,
    req,
    { params: { merchantId } }
  );
  return data;
}

export async function confirmOrders(merchantId: string, orderIds: string[], delivery: DeliveryAssignment) {
  const deliveryPayload = normalizeDeliveryPayload(delivery);
  const { data } = await apiClient.post<{ confirmed: number; orders: Order[] }>(
    "/admin/orders/confirm",
    {
      orderIds,
      delivery: deliveryPayload,
      ...deliveryPayload,
    },
    { params: { merchantId } }
  );
  return data;
}

export async function cancelOrder(merchantId: string, orderId: string, reason?: string) {
  const { data } = await apiClient.post<Order>(
    `/admin/orders/${encodeURIComponent(orderId)}/cancel`,
    reason ? { reason } : null,
    { params: { merchantId } }
  );
  return data;
}

export type OrderCylinderType = {
  code: string;
  label: string;
  minimumQuantity: number;
  maximumQuantity: number;
};

export type OrderLine = { cylinderType: string; quantity: number };

export type OrderQuote = {
  items?: OrderItem[];
  totalCylinders: number;
  totalAmount: number;
  gstPercent: number;
  subtotal: number;
  gstAmount: number;
  cutoff: Cutoff;
};

export type RepeatPreview = OrderQuote & {
  sourceOrderNumber: string;
  sourcePlacedAt: string;
  sourceItemsSummary: string;
  previousTotalAmount: number;
  priceChanged: boolean;
  unavailable?: Array<{ cylinderType: string; cylinderLabel: string; quantity: number; reason: string }>;
  canReorder: boolean;
  blockedReason?: string | null;
  deliverySiteId?: string | null;
  deliverySiteName: string;
};

export type CreateOrderInput = {
  customerId: string;
  items: OrderLine[];
  orderMode?: "NEW" | "REPEAT";
  deliverySiteId?: string | null;
};

export async function listOrderCylinderTypes(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<OrderCylinderType[]>("/admin/orders/cylinder-types", {
    params: { merchantId, customerId },
    signal
  });
  return data;
}

/** Prices a basket without placing it - the same helper the order and invoice use. */
export async function quoteOrder(merchantId: string, customerId: string, items: OrderLine[], signal?: AbortSignal) {
  const { data } = await apiClient.post<OrderQuote>("/admin/orders/quote", { customerId, items }, { params: { merchantId }, signal });
  return data;
}

/** The customer's last order priced today; 404 NO_PREVIOUS_ORDER when there is none. */
export async function getRepeatPreview(merchantId: string, customerId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<RepeatPreview>("/admin/orders/repeat", { params: { merchantId, customerId }, signal });
  return data;
}

/** `idempotencyKey` makes a retry or double-click return the first order instead of placing a second. */
export async function createOrder(merchantId: string, input: CreateOrderInput, idempotencyKey: string) {
  const { data } = await apiClient.post<Order>("/admin/orders", input, {
    params: { merchantId },
    headers: { "Idempotency-Key": idempotencyKey }
  });
  return data;
}
