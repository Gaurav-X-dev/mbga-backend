import { EditOrderDialog } from "./EditOrderDialog";
import { useOptionalAuth } from "../../auth/auth-context";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { getDelivery } from "../../api/deliveries.api";
import { normalizeError } from "../../api/errors";
import {
  createOrder,
  getOrder,
  getRepeatPreview,
  type Order,
  type RepeatPreview,
} from "../../api/orders.api";
import { getInvoice } from "../../api/payments.api";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection, Modal } from "../../components/feedback/Dialogs";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { DetailsPanel } from "../../components/layout/Page";
import { formatCurrency, formatDate, formatDateTime, formatNumber, humanize } from "../../utils/format";
import { useInvoicePdf } from "../admin-payments/useInvoicePdf";
import { formatAddress } from "./order-utils";
import { OrderTrackingTimeline } from "./OrderTrackingTimeline";

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface Props {
  merchantId: string;
  orderId: string;
  onClose: () => void;
  renderStatus: (status: string) => JSX.Element;
  onConfirm: () => void;
  onCancel: (order: Order) => void;
}

export function OrderDrawer({
  merchantId,
  orderId,
  onClose,
  renderStatus,
  onConfirm,
  onCancel,
}: Props) {
  const auth = useOptionalAuth();
  const [editing,setEditing]=useState(false);
  const toast = useToast();
  const queryClient = useQueryClient();
  const pdf = useInvoicePdf(merchantId);

  const [reorderOpen, setReorderOpen] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.orders.detail(merchantId, orderId),
    queryFn: ({ signal }) => getOrder(merchantId, orderId, signal),
  });
  const order = query.data;

  // Invoice query
  const invoice = useQuery({
    queryKey: queryKeys.payments.invoice(merchantId, order?.invoiceId ?? ""),
    queryFn: ({ signal }) => getInvoice(merchantId, order!.invoiceId!, signal),
    enabled: Boolean(order?.invoiceId),
    retry: false,
  });

  // Delivery slip query
  const deliverySlip = useQuery({
    queryKey: queryKeys.deliveries.detail(merchantId, order?.deliverySlipId ?? ""),
    queryFn: ({ signal }) => getDelivery(merchantId, order!.deliverySlipId!, signal),
    enabled: Boolean(order?.deliverySlipId),
    retry: false,
  });

  // Reorder Preview Mutation
  const repeatPreviewMutation = useMutation({
    mutationFn: () => getRepeatPreview(merchantId, order?.customerId ?? ""),
  });

  // Repeat Order Placement Mutation
  const placeRepeatMutation = useMutation({
    mutationFn: (preview: RepeatPreview) => {
      const items = (preview.items ?? []).map((i) => ({
        cylinderType: i.cylinderType,
        quantity: i.quantity,
      }));
      return createOrder(
        merchantId,
        {
          customerId: order!.customerId,
          items,
          orderMode: "REPEAT",
          deliverySiteId: preview.deliverySiteId || order?.deliverySiteId || null,
        },
        newKey()
      );
    },
    onSuccess: (newOrder) => {
      setReorderOpen(false);
      toast.success(`Repeat order ${newOrder.orderNumber} placed (${formatCurrency(newOrder.totalAmount)}).`);
      void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
    },
    onError: (err) => {
      toast.error(normalizeError(err).userMessage);
    },
  });

  const handleOpenReorder = () => {
    if (!order) return;
    setReorderOpen(true);
    repeatPreviewMutation.mutate();
  };

  const isPlaced = order?.status === "PLACED";
  const canConfirm = isPlaced;
  const canCancel = Boolean(order?.canCancel);
  const canReorder = Boolean(order && order.status !== "PLACED");

  return (
    <>
      {editing && order ? <EditOrderDialog order={order} merchantId={merchantId} onClose={() => setEditing(false)} onSaved={() => { void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all }); void queryClient.invalidateQueries({ queryKey: queryKeys.deliveries.all }); void queryClient.invalidateQueries({ queryKey: ["finance"] }); void queryClient.invalidateQueries({ queryKey: ["logistics"] }); }} /> : null}
      <Drawer
        open
        size="lg"
        title={order?.orderNumber ?? "Order"}
        subtitle={order ? `${order.customerName} · placed ${formatDateTime(order.placedAt)}` : undefined}
        meta={order ? renderStatus(order.status) : undefined}
        onClose={onClose}
        footer={
          order ? (
            <div className="row-between" style={{ width: "100%", alignItems: "center" }}>
              <div>
                {canCancel ? (
                  <Button variant="danger" icon="ban" onClick={() => onCancel(order)}>
                    Cancel order
                  </Button>
                ) : null}
              </div>
              <div className="row" style={{ gap: 8 }}>
                {order.canEdit && auth?.can("orders.update") ? <Button variant="secondary" onClick={() => setEditing(true)}>Edit / reschedule</Button> : null}
                {canReorder ? (
                  <Button variant="secondary" icon="refresh" onClick={handleOpenReorder}>
                    Reorder
                  </Button>
                ) : null}
                {canConfirm ? (
                  <Button variant="primary" icon="truck" onClick={onConfirm}>
                    Confirm & Schedule Delivery
                  </Button>
                ) : null}
              </div>
            </div>
          ) : undefined
        }
      >
        {query.isLoading ? (
          <LoadingSkeleton rows={6} label="Loading order details" />
        ) : query.error || !order ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <div className="stack-lg">
            {/* 1. DELIVERY CONFIRMATION OTP CARD (App flow parity) */}
            {order.deliveryOtp ? (
              <div
                className="card"
                style={{
                  background: "linear-gradient(135deg, var(--blue-50, #eff6ff), var(--surface, #ffffff))",
                  border: "1px solid var(--blue-200, #bfdbfe)",
                  borderRadius: 10,
                  padding: "16px 20px",
                  textAlign: "center",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, marginBottom: 4 }}>
                  <Icon name="key" size={18} color="var(--blue-600, #2563eb)" />
                  <strong style={{ fontSize: "0.95rem", color: "var(--blue-700, #1d4ed8)" }}>
                    Delivery Confirmation OTP
                  </strong>
                </div>
                <p className="text-muted text-small" style={{ margin: "0 0 12px" }}>
                  Share this 4-digit OTP with your delivery driver if the customer has no phone to hand.
                </p>
                <div
                  style={{
                    fontSize: "2rem",
                    fontWeight: 800,
                    letterSpacing: "10px",
                    color: "var(--blue-700, #1d4ed8)",
                    fontFamily: "monospace",
                    background: "var(--surface, #ffffff)",
                    display: "inline-block",
                    padding: "6px 20px 6px 30px",
                    borderRadius: 8,
                    border: "1px solid var(--blue-200, #bfdbfe)",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
                  }}
                >
                  {order.deliveryOtp}
                </div>
              </div>
            ) : null}

            {/* 2. VISUAL TRACKING TIMELINE */}
            <DrawerSection title="Tracking Timeline">
              <OrderTrackingTimeline merchantId={merchantId} order={order} />
            </DrawerSection>

            {/* 3. ORDER ITEMS & PRICING */}
            <DrawerSection title="Order Items">
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Cylinder</th>
                      <th style={{ textAlign: "right" }}>Qty</th>
                      <th style={{ textAlign: "right" }}>Unit price</th>
                      <th style={{ textAlign: "right" }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(order.items ?? []).map((item) => (
                      <tr key={item.cylinderType}>
                        <td><strong>{item.cylinderLabel}</strong></td>
                        <td style={{ textAlign: "right" }}>{formatNumber(item.quantity)}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(item.unitPrice)}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(item.lineTotal)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ marginTop: 8 }}>
                <DetailsPanel
                  items={[
                    { label: "Total Cylinders", value: formatNumber(order.totalCylinders) },
                    { label: "Subtotal", value: formatCurrency(order.subtotal) },
                    { label: `GST (${order.gstPercent}%)`, value: formatCurrency(order.gstAmount) },
                    {
                      label: "Total (GST incl.)",
                      value: <strong style={{ fontSize: "1.1rem" }}>{formatCurrency(order.totalAmount)}</strong>,
                    },
                  ]}
                />
              </div>
            </DrawerSection>

            {/* 4. DELIVERY DETAILS & ASSIGNMENT */}
            <DrawerSection title="Delivery Information">
              <DetailsPanel
                items={[
                  { label: "Delivery Site", value: order.deliverySiteName || "Registered Address" },
                  { label: "Address", value: formatAddress(order.deliveryAddress) },
                  {
                    label: "Scheduled Date",
                    value: formatDate(order.cutoff?.scheduledDeliveryDate || order.placedAt),
                  },
                  {
                    label: "Delivery Cut-off",
                    value: `${order.cutoff?.cutoffTime || "18:00"} IST (${order.cutoff?.withinCutoff ? "Within Cut-off" : "After Cut-off"})`,
                  },
                  {
                    label: "Assigned Vehicle",
                    value: deliverySlip.data?.vehicleNumber ? (
                      <span className="mono" style={{ fontWeight: 600 }}>
                        {deliverySlip.data.vehicleNumber}
                      </span>
                    ) : (
                      <span className="text-muted">Not assigned yet</span>
                    ),
                  },
                  {
                    label: "Assigned Driver",
                    value: deliverySlip.data?.driverName ? (
                      <span>{deliverySlip.data.driverName}</span>
                    ) : (
                      <span className="text-muted">Not assigned yet</span>
                    ),
                  },
                  {
                    label: "Helper",
                    value: deliverySlip.data?.helperName || "—",
                    hidden: !deliverySlip.data?.helperName,
                  },
                  {
                    label: "Delivery Slip",
                    value: order.deliverySlipId ? (
                      <span className="row" style={{ gap: 8, alignItems: "center" }}>
                        <span className="mono">{deliverySlip.data?.slipNumber || order.deliverySlipId}</span>
                        <Link className="btn btn--secondary btn--sm" to={`/admin/deliveries?merchant=${encodeURIComponent(merchantId)}`}>
                          View Slips
                        </Link>
                      </span>
                    ) : (
                      <span className="text-muted">Slip generated upon confirmation</span>
                    ),
                  },
                ]}
              />
            </DrawerSection>

            {/* 5. ORDER INFO */}
            <DrawerSection title="Customer & Order Details">
              <DetailsPanel
                items={[
                  { label: "Customer", value: `${order.customerName} (${humanize(order.customerType)})` },
                  { label: "Order Mode", value: order.orderMode === "REPEAT" ? "Repeat Order" : "New Order" },
                  {
                    label: "Placed Via",
                    value: order.source === "CUSTOMER_APP" ? "Customer App" : `Merchant App${order.createdBy ? ` (${order.createdBy})` : ""}`,
                  },
                  { label: "Order Placed At", value: formatDateTime(order.placedAt) },
                ]}
              />
            </DrawerSection>

            {/* 6. TAX INVOICE SECTION (App flow parity) */}
            <DrawerSection title="Tax Invoice">
              {order.status === "DELIVERED" && !order.invoiceId ? (
                <Alert tone="info" title="Invoice Generating">
                  Your tax invoice is being generated automatically upon delivery. It will appear here shortly.
                </Alert>
              ) : order.invoiceId ? (
                <div
                  className="stack"
                  style={{
                    padding: "14px 16px",
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    background: "var(--surface-muted, #f8fafc)",
                    gap: 10,
                  }}
                >
                  <div className="row-between" style={{ alignItems: "center" }}>
                    <div className="row" style={{ gap: 8, alignItems: "center" }}>
                      <Icon name="fileText" size={18} />
                      <strong style={{ fontSize: "1.05rem" }}>
                        {invoice.data?.invoiceNumber || "Tax Invoice"}
                      </strong>
                    </div>
                    {invoice.data ? <StatusBadge status={invoice.data.status} /> : null}
                  </div>

                  {invoice.data ? (
                    <DetailsPanel
                      items={[
                        { label: "Invoice Date", value: formatDate(invoice.data.issuedAt) },
                        { label: "Due Date", value: formatDate(invoice.data.dueAt) },
                        { label: "Total Amount", value: formatCurrency(invoice.data.totalAmount) },
                        { label: "Amount Paid", value: formatCurrency(invoice.data.paidAmount) },
                        {
                          label: "Balance Due",
                          value: <strong>{formatCurrency(invoice.data.balance)}</strong>,
                        },
                      ]}
                    />
                  ) : invoice.isLoading ? (
                    <p className="text-muted text-small">Loading invoice details…</p>
                  ) : null}

                  {invoice.data ? (
                    <div className="row" style={{ gap: 8, marginTop: 4 }}>
                      <Link
                        className="btn btn--secondary btn--sm"
                        to={`/admin/payments?merchant=${encodeURIComponent(merchantId)}&view=invoices&invoice=${encodeURIComponent(invoice.data.id)}`}
                      >
                        View in Invoices
                      </Link>
                      <Button
                        size="sm"
                        variant="secondary"
                        icon="download"
                        loading={pdf.isBusy(invoice.data.id, "download")}
                        onClick={() => void pdf.download(invoice.data!)}
                      >
                        Download PDF
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="text-muted text-small">
                  Tax invoice is issued automatically upon order delivery.
                </p>
              )}
            </DrawerSection>
          </div>
        )}
      </Drawer>

      {/* REORDER PREVIEW MODAL (Parity with merchant app reorder bottom sheet) */}
      {order ? (
        <Modal
          open={reorderOpen}
          title="Repeat Order"
          description={`Reorder based on ${order.orderNumber} (${order.itemsSummary})`}
          onClose={() => setReorderOpen(false)}
          busy={placeRepeatMutation.isPending}
          footer={
            <>
              <Button
                variant="secondary"
                onClick={() => setReorderOpen(false)}
                disabled={placeRepeatMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                icon="refresh"
                onClick={() =>
                  repeatPreviewMutation.data &&
                  placeRepeatMutation.mutate(repeatPreviewMutation.data)
                }
                disabled={!repeatPreviewMutation.data?.canReorder || placeRepeatMutation.isPending}
                loading={placeRepeatMutation.isPending}
                loadingText="Placing Repeat Order…"
              >
                Place Repeat Order
              </Button>
            </>
          }
        >
          {repeatPreviewMutation.isPending ? (
            <LoadingSkeleton rows={4} label="Checking today's price and availability…" />
          ) : repeatPreviewMutation.error ? (
            <Alert tone="error">
              {normalizeError(repeatPreviewMutation.error).userMessage}
            </Alert>
          ) : repeatPreviewMutation.data ? (
            <div className="stack-lg">
              {/* Unavailable items alert */}
              {repeatPreviewMutation.data.unavailable?.length ? (
                <Alert tone="warning" title="Some lines cannot be repeated">
                  {repeatPreviewMutation.data.unavailable
                    .map((u) => `${u.quantity} × ${u.cylinderLabel} — ${u.reason}`)
                    .join("; ")}
                </Alert>
              ) : null}

              {/* Price changed note */}
              {repeatPreviewMutation.data.priceChanged ? (
                <Alert tone="info">
                  Today's prices differ from the original order ({formatCurrency(repeatPreviewMutation.data.previousTotalAmount)} previously).
                </Alert>
              ) : null}

              {/* Blocked reason */}
              {!repeatPreviewMutation.data.canReorder && repeatPreviewMutation.data.blockedReason ? (
                <Alert tone="error">
                  {repeatPreviewMutation.data.blockedReason}
                </Alert>
              ) : null}

              {/* Items Preview Table */}
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Cylinder</th>
                      <th style={{ textAlign: "right" }}>Qty</th>
                      <th style={{ textAlign: "right" }}>Today's Unit Price</th>
                      <th style={{ textAlign: "right" }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(repeatPreviewMutation.data.items ?? []).map((it) => (
                      <tr key={it.cylinderType}>
                        <td><strong>{it.cylinderLabel}</strong></td>
                        <td style={{ textAlign: "right" }}>{it.quantity}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(it.unitPrice)}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(it.lineTotal)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <DetailsPanel
                items={[
                  { label: "Customer", value: order.customerName },
                  { label: "Delivery Site", value: repeatPreviewMutation.data.deliverySiteName || "Primary site" },
                  { label: "Total Cylinders", value: formatNumber(repeatPreviewMutation.data.totalCylinders) },
                  {
                    label: "Scheduled Delivery",
                    value: formatDate(repeatPreviewMutation.data.cutoff?.scheduledDeliveryDate),
                  },
                  {
                    label: "New Total (GST incl.)",
                    value: <strong style={{ fontSize: "1.1rem" }}>{formatCurrency(repeatPreviewMutation.data.totalAmount)}</strong>,
                  },
                ]}
              />
            </div>
          ) : null}
        </Modal>
      ) : null}
    </>
  );
}
export default OrderDrawer;
