import type { Address, Order } from "../../api/orders.api";

export function formatAddress(address: Address | null | undefined): string {
  if (!address) return "—";
  return [address.line1, address.line2, address.city, address.state, address.pincode].filter(Boolean).join(", ") || "—";
}

export function parseVehicleAssignmentError(err: unknown): string | undefined {
  if (!err) return undefined;
  const rawErr = err as any;
  const detailFields =
    rawErr?.details?.fields ||
    rawErr?.response?.data?.detail?.fields ||
    rawErr?.rawError?.detail?.fields ||
    (Array.isArray(rawErr?.fieldErrors?.fields) ? rawErr.fieldErrors.fields : undefined);

  let code: string | undefined;
  if (Array.isArray(detailFields) && detailFields[0]?.code) {
    code = String(detailFields[0].code).toLowerCase();
  } else if (rawErr?.code) {
    code = String(rawErr.code).toLowerCase();
  } else if (rawErr?.message) {
    const msg = String(rawErr.message).toLowerCase();
    if (msg.includes("vehicle_unknown") || msg.includes("unknown vehicle")) code = "vehicle_unknown";
    else if (msg.includes("vehicle_inactive") || msg.includes("inactive vehicle")) code = "vehicle_inactive";
    else if (msg.includes("vehicle_already_assigned") || msg.includes("already assigned")) code = "vehicle_already_assigned";
  }

  if (code === "vehicle_unknown") {
    return "Vehicle unknown or not found. Please select a valid vehicle.";
  }
  if (code === "vehicle_inactive") {
    return "Selected vehicle is inactive. Please select an active vehicle.";
  }
  if (code === "vehicle_already_assigned") {
    return "Selected vehicle is already assigned to another active trip.";
  }

  if (rawErr?.fieldErrors?.vehicleNumber) {
    return rawErr.fieldErrors.vehicleNumber;
  }
  if (rawErr?.fieldErrors?.vehicle) {
    return rawErr.fieldErrors.vehicle;
  }
  return undefined;
}

export function getCrewConflictMessage(err: unknown, role: "driver" | "helper"): string | undefined {
  if (!err) return undefined;
  const raw = err as any;
  const detail = raw?.response?.data?.detail;
  const message = typeof detail === "string" ? detail : (detail?.message || raw?.message || "");
  const code = String(
    (typeof detail === "object" ? detail?.code : undefined) ||
    raw?.code ||
    raw?.response?.data?.code ||
    ""
  ).toUpperCase();
  const lower = message.toLowerCase();

  if (role === "driver") {
    if (code === "DELIVERY_USER_NOT_FOUND" || lower.includes("could not find this driver") || lower.includes("delivery_user_not_found")) {
      return "Selected driver was not found. Please refresh the driver list and select an active driver.";
    }
    if (lower.includes("driver_already_assigned") || lower.includes("driver is already assigned") || lower.includes("driver conflict")) {
      return "Driver is already assigned to another active round at this time.";
    }
    if (lower.includes("driver_inactive") || lower.includes("driver is inactive")) {
      return "Selected driver is currently inactive or off-duty.";
    }
  } else {
    if (code === "DELIVERY_USER_NOT_FOUND" || lower.includes("could not find this helper") || lower.includes("delivery_user_not_found")) {
      return "Selected helper was not found. Please refresh the helper list and select an active helper.";
    }
    if (lower.includes("helper_already_assigned") || lower.includes("helper is already assigned") || lower.includes("helper conflict")) {
      return "Helper is already assigned to another active round at this time.";
    }
    if (lower.includes("helper_inactive") || lower.includes("helper is inactive")) {
      return "Selected helper is currently inactive or off-duty.";
    }
  }

  const key = role === "driver" ? "driverUserId" : "helperUserId";
  if (raw?.fieldErrors?.[key]) return raw.fieldErrors[key];
  if (raw?.fieldErrors?.[`delivery.${key}`]) return raw.fieldErrors[`delivery.${key}`];

  return undefined;
}

export type OrderRouteGroup = {
  pincode: string;
  city: string;
  label: string;
  orders: Order[];
  totalCylinders: number;
  totalAmount: number;
};

export function groupOrdersByPincode(orders: Order[]): OrderRouteGroup[] {
  const map = new Map<string, Order[]>();
  for (const order of orders) {
    const pin = order.deliveryAddress?.pincode || "General";
    const list = map.get(pin) ?? [];
    list.push(order);
    map.set(pin, list);
  }

  return Array.from(map.entries()).map(([pincode, routeOrders]) => {
    const city = routeOrders[0]?.deliveryAddress?.city || "";
    const label = city ? `${city} (${pincode})` : pincode;
    const totalCylinders = routeOrders.reduce((sum, o) => sum + (o.totalCylinders || 0), 0);
    const totalAmount = routeOrders.reduce((sum, o) => sum + (o.totalAmount || 0), 0);
    return {
      pincode,
      city,
      label,
      orders: routeOrders,
      totalCylinders,
      totalAmount,
    };
  });
}
