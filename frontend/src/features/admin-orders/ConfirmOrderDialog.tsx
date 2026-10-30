import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { listAvailableDeliveryUsers, type AdminDeliveryUser } from "../../api/delivery-users.api";
import { normalizeError } from "../../api/errors";
import {
  type DeliveryAssignment,
  type Order,
} from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import {
  listAvailableVehicles,
  listOrderEligibleVehicles,
  type EligibleVehicle,
} from "../../api/vehicles.api";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { Field, Input, Select } from "../../components/forms/Field";
import { formatCurrency, formatNumber, todayInputValue } from "../../utils/format";
import { EligibleVehicleField } from "../admin-vehicles/EligibleVehicleField";
import {
  getCrewConflictMessage,
  groupOrdersByPincode,
  parseVehicleAssignmentError,
  type OrderRouteGroup,
} from "./order-utils";

interface RouteAssignmentState {
  vehicleNumber: string;
  driverUserId: string;
  driverName: string;
  deliveryDate: string;
}

interface Props {
  open: boolean;
  merchantId: string;
  orders: Order[];
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (delivery: DeliveryAssignment) => void;
  onBulkSubmit?: (groups: { orderIds: string[]; delivery: DeliveryAssignment }[]) => void;
}

export function resolveDriverId(d?: AdminDeliveryUser | null): string {
  if (!d) return "";
  return d.user_id || d.id || (d as any).driver_id || (d as any).delivery_user_id || "";
}

export function findDriver(drivers: AdminDeliveryUser[], key?: string | null): AdminDeliveryUser | undefined {
  if (!key) return undefined;
  return drivers.find(
    (d) =>
      d.user_id === key ||
      d.id === key ||
      resolveDriverId(d) === key ||
      (d as any).driver_id === key ||
      (d as any).delivery_user_id === key
  );
}

export function ConfirmOrderDialog({
  open,
  merchantId,
  orders,
  pending,
  error,
  onClose,
  onSubmit,
  onBulkSubmit,
}: Props) {
  const isBulk = orders.length > 1;

  // Global / single assignment fields
  const [vehicleNumber, setVehicleNumber] = useState("");
  const [driverUserId, setDriverUserId] = useState("");
  const [deliveryDate, setDeliveryDate] = useState("");
  const [touched, setTouched] = useState(false);
  const [vehicleConflictError, setVehicleConflictError] = useState<string | undefined>();
  const [driverConflictError, setDriverConflictError] = useState<string | undefined>();

  // Route groupings for bulk orders
  const routeGroups: OrderRouteGroup[] = useMemo(() => {
    return isBulk ? groupOrdersByPincode(orders) : [];
  }, [isBulk, orders]);

  // Per-route assignment state for bulk
  const [routeAssignments, setRouteAssignments] = useState<Record<string, RouteAssignmentState>>({});

  // Reset form when dialog opens
  useEffect(() => {
    if (!open) return;
    const initialDate = orders[0]?.cutoff?.scheduledDeliveryDate || todayInputValue();
    setVehicleNumber("");
    setDriverUserId("");
    setDeliveryDate(initialDate);
    setTouched(false);
    setVehicleConflictError(undefined);
    setDriverConflictError(undefined);

    if (orders.length > 1) {
      const initialRoutes: Record<string, RouteAssignmentState> = {};
      const groups = groupOrdersByPincode(orders);
      groups.forEach((g) => {
        initialRoutes[g.pincode] = {
          vehicleNumber: "",
          driverUserId: "",
          driverName: "",
          deliveryDate: g.orders[0]?.cutoff?.scheduledDeliveryDate || initialDate,
        };
      });
      setRouteAssignments(initialRoutes);
    } else {
      setRouteAssignments({});
    }
  }, [open, orders]);

  // Query eligible vehicles for single order or all selected orders
  const vehicleQueries = useQueries({
    queries: orders.map((order) => ({
      queryKey: queryKeys.vehicles.forOrder(merchantId, order.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => listOrderEligibleVehicles(merchantId, order.id, signal),
      enabled: open && Boolean(merchantId) && Boolean(order.id),
      staleTime: 30_000,
      retry: false,
    })),
  });

  const allAvailableVehicles = useQuery({
    queryKey: queryKeys.vehicles.available(merchantId),
    queryFn: ({ signal }) => listAvailableVehicles(merchantId, signal),
    enabled: open && Boolean(merchantId),
    staleTime: 30_000,
  });

  const eligibleLoading = vehicleQueries.some((q) => q.isLoading) || allAvailableVehicles.isLoading;
  const eligibleFailed = vehicleQueries.some((q) => q.error);
  const eligibleLists = vehicleQueries.map((q) => q.data);

  // Common eligible vehicles across orders, or fallback to all available vehicles
  const eligibleVehicles: EligibleVehicle[] | undefined = useMemo(() => {
    if (eligibleLists.length && eligibleLists.every(Boolean)) {
      const intersection = eligibleLists[0]!.filter((v) =>
        eligibleLists.every((list) => list!.some((o) => o.id === v.id))
      );
      if (intersection.length > 0) return intersection;
    }
    return allAvailableVehicles.data?.items.map((v) => ({
      ...v,
      matchedPincode: null,
      priority: null,
    }));
  }, [eligibleLists, allAvailableVehicles.data]);

  // Live active delivery drivers query
  const driversQuery = useQuery({
    queryKey: ["admin", "delivery-users", "available", merchantId, "DRIVER"],
    queryFn: ({ signal }) => listAvailableDeliveryUsers(merchantId, "DRIVER", signal),
    enabled: open && Boolean(merchantId),
    staleTime: 30_000,
  });

  const availableDrivers = driversQuery.data?.items ?? [];

  // Parse errors whenever error prop changes
  useEffect(() => {
    if (error) {
      const vMsg = parseVehicleAssignmentError(error);
      const dMsg = getCrewConflictMessage(error, "driver");
      if (vMsg) setVehicleConflictError(vMsg);
      if (dMsg) setDriverConflictError(dMsg);
    }
  }, [error]);

  const selectedDriver = findDriver(availableDrivers, driverUserId);

  const vehicleError =
    vehicleConflictError ||
    (touched && !vehicleNumber.trim() ? "Vehicle is required for delivery assignment." : undefined);
  const driverError =
    driverConflictError ||
    (touched && !driverUserId.trim() ? "Driver selection is required." : undefined);
  const dateError =
    touched && !deliveryDate.trim() ? "Delivery date is required." : undefined;

  const memberName = (m?: AdminDeliveryUser | null) => m?.full_name || (m as any)?.name || "";
  const memberPhone = (m?: AdminDeliveryUser | null) => m?.mobile_number || (m as any)?.phone || "";

  // Apply the first route or global assignment to all route groups
  const applyAssignmentToAllRoutes = () => {
    if (!routeGroups.length) return;
    const targetVehicle = vehicleNumber.trim();
    const selDriver = findDriver(availableDrivers, driverUserId);
    const targetDriverId = resolveDriverId(selDriver) || driverUserId;
    const targetDriver = memberName(selDriver);
    const targetDate = deliveryDate;

    setRouteAssignments((prev) => {
      const next: Record<string, RouteAssignmentState> = {};
      routeGroups.forEach((g) => {
        next[g.pincode] = {
          vehicleNumber: targetVehicle || prev[g.pincode]?.vehicleNumber || "",
          driverUserId: targetDriverId || prev[g.pincode]?.driverUserId || "",
          driverName: targetDriver || prev[g.pincode]?.driverName || "",
          deliveryDate: targetDate || prev[g.pincode]?.deliveryDate || "",
        };
      });
      return next;
    });
  };

  const updateRouteAssignment = (pincode: string, field: keyof RouteAssignmentState, value: string) => {
    setRouteAssignments((prev) => {
      const current = prev[pincode] || {
        vehicleNumber: "",
        driverUserId: "",
        driverName: "",
        deliveryDate: "",
      };
      return {
        ...prev,
        [pincode]: {
          ...current,
          [field]: value,
        },
      };
    });
  };

  const handleSubmit = () => {
    setTouched(true);
    setVehicleConflictError(undefined);
    setDriverConflictError(undefined);

    if (isBulk && onBulkSubmit && routeGroups.length > 1) {
      // Validate each route
      let valid = true;
      for (const g of routeGroups) {
        const a = routeAssignments[g.pincode];
        if (!a?.vehicleNumber.trim() || !a?.driverUserId.trim() || !a?.deliveryDate.trim()) {
          valid = false;
        }
      }
      if (!valid) {
        // Fallback to global if set
        if (!vehicleNumber.trim() || !driverUserId.trim() || !deliveryDate.trim()) return;
      }

      const groupsPayload = routeGroups.map((g) => {
        const a = routeAssignments[g.pincode];
        const vNum = (a?.vehicleNumber.trim() || vehicleNumber.trim()).toUpperCase();
        const dId = a?.driverUserId.trim() || driverUserId.trim();
        const dObj = findDriver(availableDrivers, dId);
        const finalDriverId = resolveDriverId(dObj) || dId;
        const memberRowId = dObj?.id || finalDriverId;
        const dDate = a?.deliveryDate.trim() || deliveryDate.trim();

        return {
          orderIds: g.orders.map((o) => o.id),
          delivery: {
            vehicleNumber: vNum,
            vehicle_number: vNum,
            driverUserId: finalDriverId || null,
            driver_user_id: finalDriverId || null,
            driverId: finalDriverId || null,
            driver_id: finalDriverId || null,
            deliveryUserId: memberRowId || null,
            delivery_user_id: memberRowId || null,
            driverName: memberName(dObj) || null,
            driver_name: memberName(dObj) || null,
            deliveryDate: dDate || null,
            delivery_date: dDate || null,
          },
        };
      });

      onBulkSubmit(groupsPayload);
      return;
    }

    if (!vehicleNumber.trim() || !driverUserId.trim() || !deliveryDate.trim()) {
      return;
    }

    const selDriver = findDriver(availableDrivers, driverUserId);
    const finalDriverUserId = resolveDriverId(selDriver) || driverUserId;
    const memberRowId = selDriver?.id || finalDriverUserId;

    onSubmit({
      vehicleNumber: vehicleNumber.trim().toUpperCase(),
      vehicle_number: vehicleNumber.trim().toUpperCase(),
      driverUserId: finalDriverUserId || null,
      driver_user_id: finalDriverUserId || null,
      driverId: finalDriverUserId || null,
      driver_id: finalDriverUserId || null,
      deliveryUserId: memberRowId || null,
      delivery_user_id: memberRowId || null,
      driverName: memberName(selDriver) || null,
      driver_name: memberName(selDriver) || null,
      deliveryDate: deliveryDate || null,
      delivery_date: deliveryDate || null,
    });
  };

  const hasNoVehiclesForPincode =
    !eligibleLoading && (!eligibleVehicles || eligibleVehicles.length === 0);

  return (
    <Modal
      open={open}
      wide={isBulk}
      title={isBulk ? `Confirm & Assign ${orders.length} Orders` : "Confirm & Schedule Delivery"}
      description={
        isBulk
          ? "Assign delivery vans and crew for the selected orders. Orders can be routed together by pincode."
          : "Accept order, assign an active van, driver and set scheduled delivery date."
      }
      onClose={onClose}
      busy={pending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon="truck"
            onClick={handleSubmit}
            loading={pending}
            loadingText="Confirming…"
          >
            Confirm & Assign Delivery
          </Button>
        </>
      }
    >
      <form
        className="stack"
        style={{ gap: 14 }}
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit();
        }}
      >
        {/* Pincode Warning Banner */}
        {hasNoVehiclesForPincode ? (
          <Alert tone="warning" title="No vehicle mapped to this pincode">
            No vehicle is currently mapped to this delivery pincode. You can type a vehicle registration number manually.
          </Alert>
        ) : null}

        {/* Global / Single Order Fields */}
        <div className="stack" style={{ gap: 14 }}>
          {/* 1. Vehicle Selection */}
          <EligibleVehicleField
            selectedDriverUserId={driverUserId}
            vehicles={eligibleVehicles}
            loading={eligibleLoading}
            failed={eligibleFailed}
            value={vehicleNumber}
            onChange={(val) => {
              setVehicleNumber(val);
              setVehicleConflictError(undefined);
            }}
            error={vehicleError}
            autoFocus
          />

          {/* 2. Driver Selection & Scheduled Delivery Date */}
          <div className="grid-2" style={{ gap: 12 }}>
            <Field
              label={
                <div className="row-between" style={{ alignItems: "center", width: "100%" }}>
                  <span>Driver Name</span>
                  <button
                    type="button"
                    className="btn--link"
                    style={{ fontSize: "0.8rem", display: "inline-flex", alignItems: "center", gap: 4 }}
                    onClick={() => driversQuery.refetch()}
                    disabled={driversQuery.isFetching}
                  >
                    <Icon name="refresh" size={13} />
                    <span>{driversQuery.isFetching ? "Refreshing…" : "Refresh"}</span>
                  </button>
                </div>
              }
              required
              error={driverError}
              hint={
                driversQuery.isLoading
                  ? "Loading active drivers…"
                  : availableDrivers.length === 0
                    ? "No active drivers available right now."
                    : `${availableDrivers.length} drivers available on duty.`
              }
            >
              <Select
                value={driverUserId}
                disabled={driversQuery.isLoading}
                onChange={(e) => {
                  setDriverUserId(e.target.value);
                  setDriverConflictError(undefined);
                }}
                placeholder={driversQuery.isLoading ? "Loading drivers…" : "Select an active driver"}
                options={availableDrivers.map((d) => ({
                  value: resolveDriverId(d),
                  label: `${memberName(d)}${memberPhone(d) ? ` (${memberPhone(d)})` : ""}`,
                }))}
              />
            </Field>

            <Field label="Scheduled Delivery Date" required error={dateError}>
              <Input
                type="date"
                min={todayInputValue()}
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
              />
            </Field>
          </div>
        </div>

        {/* Bulk Route Grouping Section */}
        {isBulk && routeGroups.length > 0 ? (
          <div
            className="stack"
            style={{
              gap: 12,
              padding: 16,
              borderRadius: 8,
              background: "var(--surface-muted, #f8fafc)",
              border: "1px solid var(--border)",
            }}
          >
            <div className="row-between" style={{ alignItems: "center" }}>
              <div className="stack" style={{ gap: 2 }}>
                <strong>Delivery Routes ({routeGroups.length} Pincodes)</strong>
                <small className="text-muted">
                  {orders.length} orders total · {orders.reduce((s, o) => s + o.totalCylinders, 0)} cylinders
                </small>
              </div>
              <Button
                variant="secondary"
                size="sm"
                icon="check"
                onClick={applyAssignmentToAllRoutes}
              >
                Apply Selection to All Routes
              </Button>
            </div>

            <div className="stack" style={{ gap: 10 }}>
              {routeGroups.map((group) => {
                const a = routeAssignments[group.pincode] || {
                  vehicleNumber,
                  driverUserId,
                  deliveryDate,
                };
                return (
                  <div
                    key={group.pincode}
                    style={{
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      padding: "10px 14px",
                    }}
                  >
                    <div className="row-between" style={{ marginBottom: 8, alignItems: "center" }}>
                      <span className="row" style={{ gap: 8, alignItems: "center" }}>
                        <span className="badge badge--neutral" style={{ fontWeight: 600 }}>
                          PIN: {group.pincode}
                        </span>
                        <strong>{group.city || group.label}</strong>
                      </span>
                      <small className="text-muted">
                        {group.orders.length} orders · {group.totalCylinders} cylinders · {formatCurrency(group.totalAmount)}
                      </small>
                    </div>

                    <div className="grid-3" style={{ gap: 8 }}>
                      <Field label="Vehicle" hideLabel>
                        <Input
                          placeholder="Vehicle No."
                          value={a.vehicleNumber}
                          onChange={(e) =>
                            updateRouteAssignment(group.pincode, "vehicleNumber", e.target.value.toUpperCase())
                          }
                        />
                      </Field>
                      <Field label="Driver" hideLabel>
                        <Select
                          value={a.driverUserId}
                          onChange={(e) =>
                            updateRouteAssignment(group.pincode, "driverUserId", e.target.value)
                          }
                          placeholder="Select driver"
                          options={availableDrivers.map((d) => ({
                            value: resolveDriverId(d),
                            label: memberName(d),
                          }))}
                        />
                      </Field>
                      <Field label="Date" hideLabel>
                        <Input
                          type="date"
                          min={todayInputValue()}
                          value={a.deliveryDate}
                          onChange={(e) =>
                            updateRouteAssignment(group.pincode, "deliveryDate", e.target.value)
                          }
                        />
                      </Field>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* Global Error Banner */}
        {error && !vehicleConflictError && !driverConflictError ? (
          <Alert tone="error">{normalizeError(error).userMessage}</Alert>
        ) : null}
      </form>
    </Modal>
  );
}
export default ConfirmOrderDialog;
