import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { listAvailableDeliveryUsers, type AdminDeliveryUser } from "../../api/delivery-users.api";
import {
  cancelOrder,
  confirmOrder,
  confirmOrders,
  type DeliveryAssignment,
  type Order,
} from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import {
  listAvailableVehicles,
  listOrderEligibleVehicles,
  type EligibleVehicle,
  type Vehicle,
} from "../../api/vehicles.api";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { formatCurrency, formatDate, formatNumber, todayInputValue } from "../../utils/format";
import { findDriver, resolveDriverId } from "./ConfirmOrderDialog";
import {
  getCrewConflictMessage,
  groupOrdersByPincode,
  parseVehicleAssignmentError,
  type OrderRouteGroup,
} from "./order-utils";

export type BulkActionChoice = "CONFIRM" | "CANCEL";

interface RouteAssignmentState {
  vehicleNumber: string;
  driverUserId: string;
  deliveryDate: string;
}

interface Props {
  open: boolean;
  merchantId: string;
  orders: Order[];
  initialAction?: BulkActionChoice;
  onClose: () => void;
  onSuccess?: () => void;
}

export function OrderBulkActionDialog({
  open,
  merchantId,
  orders,
  initialAction = "CONFIRM",
  onClose,
  onSuccess,
}: Props) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const [statusChoice, setStatusChoice] = useState<BulkActionChoice>(initialAction);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);

  // Cancellation state
  const [cancelReason, setCancelReason] = useState("");
  const [cancelTouched, setCancelTouched] = useState(false);

  // Confirmation state
  const [globalVehicleNumber, setGlobalVehicleNumber] = useState("");
  const [globalDriverUserId, setGlobalDriverUserId] = useState("");
  const [globalDeliveryDate, setGlobalDeliveryDate] = useState("");
  const [routeAssignments, setRouteAssignments] = useState<Record<string, RouteAssignmentState>>({});
  const [expandedRoutes, setExpandedRoutes] = useState<Record<string, boolean>>({});
  const [confirmTouched, setConfirmTouched] = useState(false);
  const [vehicleConflictError, setVehicleConflictError] = useState<string | undefined>();
  const [driverConflictError, setDriverConflictError] = useState<string | undefined>();

  // Cancellable vs non-cancellable
  const cancellableOrders = useMemo(
    () => orders.filter((o) => o.status === "PLACED" || o.canCancel !== false),
    [orders]
  );
  const nonCancellableCount = orders.length - cancellableOrders.length;

  // Confirmable orders (status === "PLACED")
  const confirmableOrders = useMemo(
    () => orders.filter((o) => o.status === "PLACED"),
    [orders]
  );
  const nonConfirmableCount = orders.length - confirmableOrders.length;

  // Route groupings by destination pincode
  const routeGroups: OrderRouteGroup[] = useMemo(() => {
    return groupOrdersByPincode(confirmableOrders);
  }, [confirmableOrders]);

  // Reset / initialize state on open
  useEffect(() => {
    if (!open) return;
    setStatusChoice(initialAction);
    setGeneralError(null);
    setCancelReason("");
    setCancelTouched(false);
    setConfirmTouched(false);
    setVehicleConflictError(undefined);
    setDriverConflictError(undefined);

    const defaultDate =
      orders[0]?.cutoff?.scheduledDeliveryDate || todayInputValue();
    setGlobalDeliveryDate(defaultDate);
    setGlobalVehicleNumber("");
    setGlobalDriverUserId("");

    const initialRoutes: Record<string, RouteAssignmentState> = {};
    const initialExpanded: Record<string, boolean> = {};
    const groups = groupOrdersByPincode(orders.filter((o) => o.status === "PLACED"));
    groups.forEach((g) => {
      initialRoutes[g.pincode] = {
        vehicleNumber: "",
        driverUserId: "",
        deliveryDate: g.orders[0]?.cutoff?.scheduledDeliveryDate || defaultDate,
      };
      initialExpanded[g.pincode] = true;
    });
    setRouteAssignments(initialRoutes);
    setExpandedRoutes(initialExpanded);
  }, [open, orders, initialAction]);

  // Live queries for fleet vehicles and drivers
  const vehiclesQuery = useQuery({
    queryKey: queryKeys.vehicles.available(merchantId),
    queryFn: ({ signal }) => listAvailableVehicles(merchantId, signal),
    enabled: open && Boolean(merchantId),
    staleTime: 30_000,
  });

  const driversQuery = useQuery({
    queryKey: ["admin", "delivery-users", "available", merchantId, "DRIVER"],
    queryFn: ({ signal }) => listAvailableDeliveryUsers(merchantId, "DRIVER", signal),
    enabled: open && Boolean(merchantId),
    staleTime: 30_000,
  });

  const availableVehicles: Vehicle[] = vehiclesQuery.data?.items ?? [];
  const availableDrivers: AdminDeliveryUser[] = driversQuery.data?.items ?? [];

  // Pincode vehicle options
  const getVehicleOptionsForRoute = (pincode: string) => {
    if (!availableVehicles.length) return [];
    const directMatches = availableVehicles.filter((v: any) =>
      v.assignedPincodes?.includes(pincode) || v.pincodes?.includes(pincode)
    );
    const otherVehicles = availableVehicles.filter(
      (v: any) => !v.assignedPincodes?.includes(pincode) && !v.pincodes?.includes(pincode)
    );

    const options = [
      ...directMatches.map((v) => ({
        value: v.number,
        label: `${v.number} • ${v.label || "Van"} (Pincode match)`,
      })),
      ...otherVehicles.map((v) => ({
        value: v.number,
        label: `${v.number} • ${v.label || "Available"}`,
      })),
    ];
    return options;
  };

  const driverOptions = useMemo(() => {
    return availableDrivers.map((d) => {
      const id = resolveDriverId(d);
      const name = d.full_name || (d as any).name || "Driver";
      const duty = d.on_duty ? " • On duty" : " • Off duty";
      const phone = d.mobile_number ? ` (${d.mobile_number})` : "";
      return {
        value: id,
        label: `${name}${phone}${duty}`,
      };
    });
  }, [availableDrivers]);

  // Copy Route 1 or global assignment to all route groups
  const applyRoute1ToAll = () => {
    if (!routeGroups.length) return;
    const firstPincode = routeGroups[0].pincode;
    const source = routeAssignments[firstPincode] || {
      vehicleNumber: globalVehicleNumber,
      driverUserId: globalDriverUserId,
      deliveryDate: globalDeliveryDate,
    };

    if (!source.vehicleNumber && !source.driverUserId && !source.deliveryDate) {
      toast.show("Please fill in a vehicle, driver or delivery date on Route 1 first.", "info");
      return;
    }

    setRouteAssignments((prev) => {
      const next: Record<string, RouteAssignmentState> = {};
      routeGroups.forEach((g) => {
        next[g.pincode] = {
          vehicleNumber: source.vehicleNumber || prev[g.pincode]?.vehicleNumber || "",
          driverUserId: source.driverUserId || prev[g.pincode]?.driverUserId || "",
          deliveryDate: source.deliveryDate || prev[g.pincode]?.deliveryDate || "",
        };
      });
      return next;
    });

    toast.success("Applied vehicle, driver and delivery date to all delivery routes.");
  };

  const updateRoute = (pincode: string, field: keyof RouteAssignmentState, value: string) => {
    setRouteAssignments((prev) => {
      const current = prev[pincode] || {
        vehicleNumber: "",
        driverUserId: "",
        deliveryDate: globalDeliveryDate,
      };
      return {
        ...prev,
        [pincode]: {
          ...current,
          [field]: value,
        },
      };
    });
    // Keep global values in sync if single route
    if (routeGroups.length === 1) {
      if (field === "vehicleNumber") setGlobalVehicleNumber(value);
      if (field === "driverUserId") setGlobalDriverUserId(value);
      if (field === "deliveryDate") setGlobalDeliveryDate(value);
    }
  };

  // Execution: Cancel
  const handleCancelSubmit = async () => {
    setCancelTouched(true);
    setGeneralError(null);
    if (!cancelReason.trim()) return;

    if (!cancellableOrders.length) {
      setGeneralError("None of the selected orders can be cancelled.");
      return;
    }

    setSubmitting(true);
    let successCount = 0;
    const failedOrders: { orderNumber: string; error: string }[] = [];

    for (const order of cancellableOrders) {
      try {
        await cancelOrder(merchantId, order.id, cancelReason.trim());
        successCount++;
      } catch (err: any) {
        failedOrders.push({
          orderNumber: order.orderNumber,
          error: err?.message || "Failed to cancel",
        });
      }
    }

    setSubmitting(false);

    if (successCount > 0) {
      toast.success(
        successCount === 1
          ? `${cancellableOrders[0].orderNumber} was cancelled.`
          : `${successCount} orders were successfully cancelled.`
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
      onSuccess?.();
      onClose();
    } else {
      setGeneralError(
        failedOrders.map((f) => `${f.orderNumber}: ${f.error}`).join("; ") ||
          "Failed to cancel selected orders."
      );
    }
  };

  // Execution: Confirm & Schedule
  const handleConfirmSubmit = async () => {
    setConfirmTouched(true);
    setGeneralError(null);
    setVehicleConflictError(undefined);
    setDriverConflictError(undefined);

    if (!confirmableOrders.length) {
      setGeneralError("None of the selected orders are awaiting confirmation.");
      return;
    }

    // Validate all routes
    let allValid = true;
    for (const g of routeGroups) {
      const a = routeAssignments[g.pincode];
      const vNum = a?.vehicleNumber?.trim() || globalVehicleNumber.trim();
      const dId = a?.driverUserId?.trim() || globalDriverUserId.trim();
      const dDate = a?.deliveryDate?.trim() || globalDeliveryDate.trim();
      if (!vNum || !dId || !dDate) {
        allValid = false;
        break;
      }
    }

    if (!allValid) {
      setGeneralError("Please select a vehicle, driver, and scheduled delivery date for all routes.");
      return;
    }

    setSubmitting(true);

    try {
      let totalConfirmed = 0;

      // Confirm each route group
      for (const g of routeGroups) {
        const a = routeAssignments[g.pincode];
        const vNum = (a?.vehicleNumber?.trim() || globalVehicleNumber.trim()).toUpperCase();
        const dId = a?.driverUserId?.trim() || globalDriverUserId.trim();
        const dDate = a?.deliveryDate?.trim() || globalDeliveryDate.trim();
        const driverObj = findDriver(availableDrivers, dId);
        const resolvedId = resolveDriverId(driverObj) || dId;
        const driverName = driverObj?.full_name || (driverObj as any)?.name || undefined;

        const delivery: DeliveryAssignment = {
          vehicleNumber: vNum,
          vehicle_number: vNum,
          driverUserId: resolvedId || undefined,
          driver_user_id: resolvedId || undefined,
          driverId: resolvedId || undefined,
          driver_id: resolvedId || undefined,
          deliveryUserId: driverObj?.id || resolvedId || undefined,
          delivery_user_id: driverObj?.id || resolvedId || undefined,
          driverName: driverName,
          driver_name: driverName,
          deliveryDate: dDate,
          delivery_date: dDate,
        };

        const ids = g.orders.map((o) => o.id);
        if (ids.length === 1) {
          await confirmOrder(merchantId, ids[0], delivery);
          totalConfirmed += 1;
        } else {
          const res = await confirmOrders(merchantId, ids, delivery);
          totalConfirmed += res.confirmed || ids.length;
        }
      }

      setSubmitting(false);
      toast.success(
        totalConfirmed === 1
          ? "1 order confirmed and delivery scheduled."
          : `${totalConfirmed} orders confirmed on delivery vans.`
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.deliveries.all });
      onSuccess?.();
      onClose();
    } catch (err: any) {
      setSubmitting(false);
      const vMsg = parseVehicleAssignmentError(err);
      const dMsg = getCrewConflictMessage(err, "driver");
      if (vMsg) setVehicleConflictError(vMsg);
      if (dMsg) setDriverConflictError(dMsg);
      setGeneralError(vMsg || dMsg || err?.message || "Failed to confirm orders.");
    }
  };

  const totalCylinders = orders.reduce((sum, o) => sum + (o.totalCylinders || 0), 0);
  const totalAmount = orders.reduce((sum, o) => sum + (o.totalAmount || 0), 0);

  return (
    <Modal
      open={open}
      wide
      title="Update orders (Bulk actions)"
      description={`${orders.length} order${orders.length === 1 ? "" : "s"} selected · ${formatNumber(totalCylinders)} cylinders · ${formatCurrency(totalAmount)}`}
      onClose={() => !submitting && onClose()}
      busy={submitting}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          {statusChoice === "CANCEL" ? (
            <Button
              variant="danger"
              icon="ban"
              onClick={() => void handleCancelSubmit()}
              loading={submitting}
              loadingText="Cancelling…"
              disabled={cancellableOrders.length === 0}
            >
              Cancel {cancellableOrders.length} order{cancellableOrders.length === 1 ? "" : "s"}
            </Button>
          ) : (
            <Button
              icon="truck"
              onClick={() => void handleConfirmSubmit()}
              loading={submitting}
              loadingText="Confirming…"
              disabled={confirmableOrders.length === 0}
            >
              Confirm & Schedule {confirmableOrders.length} order{confirmableOrders.length === 1 ? "" : "s"}
            </Button>
          )}
        </>
      }
    >
      <div className="stack-lg">
        {/* 1. Status Choice Selector (Parity with Mobile App StatusChoice cards) */}
        <div>
          <label className="field__label" style={{ marginBottom: 8, display: "block", fontWeight: 600 }}>
            Choose Action
          </label>
          <div className="status-choice-grid">
            <button
              type="button"
              className={`status-choice-card ${statusChoice === "CONFIRM" ? "is-selected" : ""}`}
              onClick={() => {
                setStatusChoice("CONFIRM");
                setGeneralError(null);
              }}
            >
              <div className="status-choice-card__icon">
                <Icon name="truck" size={20} />
              </div>
              <div className="status-choice-card__body">
                <strong>Confirm & Schedule</strong>
                <p>Assign vehicle, live driver & scheduled delivery date by route</p>
              </div>
            </button>

            <button
              type="button"
              className={`status-choice-card status-choice-card--danger ${statusChoice === "CANCEL" ? "is-selected" : ""}`}
              onClick={() => {
                setStatusChoice("CANCEL");
                setGeneralError(null);
              }}
            >
              <div className="status-choice-card__icon">
                <Icon name="ban" size={20} />
              </div>
              <div className="status-choice-card__body">
                <strong>Cancel Orders</strong>
                <p>Cancel selected orders and record cancellation reason</p>
              </div>
            </button>
          </div>
        </div>

        {generalError ? (
          <Alert tone="error" title="Action failed">
            {generalError}
          </Alert>
        ) : null}

        {/* 2. CANCEL SECTION */}
        {statusChoice === "CANCEL" ? (
          <div className="stack-md">
            {nonCancellableCount > 0 ? (
              <Alert tone="warning" title="Some orders will be skipped">
                {cancellableOrders.length === 0
                  ? "None of the selected orders can be cancelled (already delivered or cancelled)."
                  : `${nonCancellableCount} of ${orders.length} selected orders cannot be cancelled and will be skipped.`}
              </Alert>
            ) : null}

            <Field
              label="Cancellation reason"
              required
              hint="Explain why these orders are being cancelled (saved to order audit log)"
              error={cancelTouched && !cancelReason.trim() ? "Cancellation reason is required." : undefined}
            >
              <Textarea
                value={cancelReason}
                onChange={(e) => {
                  setCancelReason(e.target.value);
                  setGeneralError(null);
                }}
                maxLength={255}
                rows={3}
                placeholder="e.g. Customer requested cancellation / duplicate order"
                autoFocus
              />
            </Field>

            <div
              style={{
                padding: "12px 16px",
                background: "var(--surface-muted, #f8fafc)",
                borderRadius: 8,
                border: "1px solid var(--border, #e2e8f0)",
                fontSize: "0.85rem",
              }}
            >
              <strong>Orders to cancel:</strong>
              <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {cancellableOrders.map((o) => (
                  <span
                    key={o.id}
                    style={{
                      padding: "2px 8px",
                      background: "var(--surface, #ffffff)",
                      border: "1px solid var(--border, #cbd5e1)",
                      borderRadius: 4,
                      fontSize: "0.8rem",
                      fontWeight: 600,
                    }}
                  >
                    {o.orderNumber}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {/* 3. CONFIRM & SCHEDULE SECTION */}
        {statusChoice === "CONFIRM" ? (
          <div className="stack-md">
            {nonConfirmableCount > 0 ? (
              <Alert tone="info" title="Skipping non-placed orders">
                {nonConfirmableCount} selected order{nonConfirmableCount === 1 ? " is" : "s are"} already confirmed or dispatched and will be skipped.
              </Alert>
            ) : null}

            {/* Multi-route header & Quick "Apply Route 1 to All" action */}
            {routeGroups.length > 1 ? (
              <div className="multi-route-banner">
                <div className="row-between" style={{ alignItems: "center", width: "100%", flexWrap: "wrap", gap: 8 }}>
                  <div className="row" style={{ gap: 8, alignItems: "center" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        background: "var(--blue-100, #dbeafe)",
                        color: "var(--blue-700, #1d4ed8)",
                      }}
                    >
                      <Icon name="truck" size={16} />
                    </span>
                    <div>
                      <strong style={{ color: "var(--blue-700, #1d4ed8)", fontSize: "0.95rem" }}>
                        {routeGroups.length} Delivery Routes (Pincodes)
                      </strong>
                      <p className="text-muted text-small" style={{ margin: 0 }}>
                        Orders organized by destination pincode. Assign different vans or copy Route 1 to all.
                      </p>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon="copy"
                    onClick={applyRoute1ToAll}
                    title="Copy Route 1 vehicle, driver & date to all other routes"
                  >
                    Apply Route 1 to All
                  </Button>
                </div>
              </div>
            ) : null}

            {vehicleConflictError ? (
              <Alert tone="warning" title="Vehicle notice">
                {vehicleConflictError}
              </Alert>
            ) : null}

            {driverConflictError ? (
              <Alert tone="warning" title="Driver notice">
                {driverConflictError}
              </Alert>
            ) : null}

            {/* Pincode Route Assignment Cards */}
            <div className="stack-md">
              {routeGroups.map((group, groupIdx) => {
                const routeState = routeAssignments[group.pincode] || {
                  vehicleNumber: globalVehicleNumber,
                  driverUserId: globalDriverUserId,
                  deliveryDate: globalDeliveryDate,
                };
                const vehicleOpts = getVehicleOptionsForRoute(group.pincode);
                const isExpanded = expandedRoutes[group.pincode] ?? true;
                const routeCylinders = group.orders.reduce(
                  (sum, o) => sum + (o.totalCylinders || 0),
                  0
                );
                const routeTotal = group.orders.reduce(
                  (sum, o) => sum + (o.totalAmount || 0),
                  0
                );

                return (
                  <div
                    key={group.pincode}
                    className="route-card"
                    style={{
                      border: "1px solid var(--border, #e2e8f0)",
                      borderRadius: 10,
                      background: "var(--surface, #ffffff)",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                      overflow: "hidden",
                    }}
                  >
                    {/* Route Header */}
                    <div
                      style={{
                        padding: "12px 16px",
                        background: "var(--surface-muted, #f8fafc)",
                        borderBottom: "1px solid var(--border, #e2e8f0)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: 8,
                      }}
                    >
                      <div className="row" style={{ gap: 8, alignItems: "center" }}>
                        <span
                          style={{
                            padding: "3px 8px",
                            background: "var(--blue-600, #2563eb)",
                            color: "#ffffff",
                            borderRadius: 6,
                            fontWeight: 700,
                            fontSize: "0.82rem",
                          }}
                        >
                          Route {groupIdx + 1}
                        </span>
                        <strong style={{ fontSize: "0.95rem" }}>
                          PIN: {group.pincode}
                        </strong>
                        <span className="text-muted text-small">
                          ({group.orders[0]?.deliveryAddress?.city || "Local"})
                        </span>
                      </div>
                      <div className="row" style={{ gap: 12, alignItems: "center" }}>
                        <span className="text-muted text-small">
                          <strong>{group.orders.length}</strong> order{group.orders.length === 1 ? "" : "s"} · <strong>{formatNumber(routeCylinders)}</strong> cyl · <strong>{formatCurrency(routeTotal)}</strong>
                        </span>
                        <button
                          type="button"
                          className="btn--link"
                          style={{ fontSize: "0.82rem" }}
                          onClick={() =>
                            setExpandedRoutes((prev) => ({
                              ...prev,
                              [group.pincode]: !isExpanded,
                            }))
                          }
                        >
                          {isExpanded ? "Hide orders" : "View orders"}
                        </button>
                      </div>
                    </div>

                    {/* Route Form Fields */}
                    <div style={{ padding: "16px" }} className="stack-md">
                      <div className="form-grid form-grid--3">
                        {/* 1. Vehicle Selection */}
                        <Field
                          label="Delivery vehicle"
                          required
                          error={
                            confirmTouched && !routeState.vehicleNumber?.trim()
                              ? "Vehicle required"
                              : undefined
                          }
                        >
                          <Select
                            value={routeState.vehicleNumber}
                            onChange={(e) =>
                              updateRoute(group.pincode, "vehicleNumber", e.target.value)
                            }
                            placeholder="Select vehicle"
                            options={[
                              ...vehicleOpts,
                              ...(routeState.vehicleNumber &&
                              !vehicleOpts.some((v) => v.value === routeState.vehicleNumber)
                                ? [
                                    {
                                      value: routeState.vehicleNumber,
                                      label: routeState.vehicleNumber,
                                    },
                                  ]
                                : []),
                            ]}
                          />
                        </Field>

                        {/* 2. Driver Selection */}
                        <Field
                          label="Assigned driver"
                          required
                          error={
                            confirmTouched && !routeState.driverUserId?.trim()
                              ? "Driver required"
                              : undefined
                          }
                        >
                          <Select
                            value={routeState.driverUserId}
                            onChange={(e) =>
                              updateRoute(group.pincode, "driverUserId", e.target.value)
                            }
                            placeholder={
                              driversQuery.isLoading
                                ? "Loading live drivers…"
                                : "Select on-duty driver"
                            }
                            disabled={driversQuery.isLoading}
                            options={driverOptions}
                          />
                        </Field>

                        {/* 3. Scheduled Date */}
                        <Field
                          label="Delivery date"
                          required
                          error={
                            confirmTouched && !routeState.deliveryDate?.trim()
                              ? "Date required"
                              : undefined
                          }
                        >
                          <Input
                            type="date"
                            value={routeState.deliveryDate}
                            onChange={(e) =>
                              updateRoute(group.pincode, "deliveryDate", e.target.value)
                            }
                          />
                        </Field>
                      </div>

                      {/* Collapsible Order list inside route */}
                      {isExpanded ? (
                        <div
                          style={{
                            background: "var(--surface-muted, #f8fafc)",
                            padding: "10px 12px",
                            borderRadius: 6,
                            border: "1px dashed var(--border, #cbd5e1)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: "0.78rem",
                              fontWeight: 700,
                              textTransform: "uppercase",
                              color: "var(--text-muted)",
                              marginBottom: 6,
                            }}
                          >
                            Orders in this route:
                          </div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                            {group.orders.map((ord) => (
                              <div
                                key={ord.id}
                                style={{
                                  background: "var(--surface, #ffffff)",
                                  padding: "4px 8px",
                                  borderRadius: 4,
                                  border: "1px solid var(--border, #e2e8f0)",
                                  fontSize: "0.82rem",
                                }}
                              >
                                <span style={{ fontWeight: 600 }}>{ord.orderNumber}</span>
                                <span className="text-muted"> · {ord.customerName}</span>
                                <span style={{ color: "var(--blue-700, #1d4ed8)", fontWeight: 500 }}>
                                  {" "}· {ord.itemsSummary}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

export default OrderBulkActionDialog;
