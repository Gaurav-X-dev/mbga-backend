import { useQuery } from "@tanstack/react-query";
import { Icon } from "../../components/common/Icon";
import { formatDateTime } from "../../utils/format";
import { listOrderStatuses, type Order, type OrderStatusMeta } from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";

const DEFAULT_STATUSES: OrderStatusMeta[] = [
  { code: "PLACED", label: "Order Placed", sequence: 10, tone: "info", description: "Customer placed the order", isTerminal: false },
  { code: "CONFIRMED", label: "Confirmed & Scheduled", sequence: 20, tone: "info", description: "Van & driver assigned", isTerminal: false },
  { code: "OUT_FOR_DELIVERY", label: "Out for Delivery", sequence: 30, tone: "info", description: "Driver is on the road", isTerminal: false },
  { code: "DELIVERED", label: "Delivered", sequence: 40, tone: "success", description: "Delivered to customer with OTP", isTerminal: true },
  { code: "CANCELLED", label: "Cancelled", sequence: 99, tone: "error", description: "Order was cancelled", isTerminal: true },
];

interface Props {
  merchantId: string;
  order: Order;
}

export function OrderTrackingTimeline({ merchantId, order }: Props) {
  const statusesQuery = useQuery({
    queryKey: queryKeys.orders.statuses(merchantId),
    queryFn: ({ signal }) => listOrderStatuses(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 5 * 60_000,
  });

  const statuses = statusesQuery.data?.length ? statusesQuery.data : DEFAULT_STATUSES;
  const currentStatus = order.status;
  const history = order.statusHistory ?? [];
  const current = statuses.find((s) => s.code === currentStatus);
  const isCancelled = currentStatus === "CANCELLED";

  // Build steps list:
  // If cancelled, show all steps that occurred before cancellation, followed by Cancelled.
  // Otherwise, filter out error-terminal steps (like Cancelled) and show the standard pipeline.
  const steps = isCancelled
    ? statuses
        .filter((s) => s.sequence < (current?.sequence ?? 99) && history.some((h) => h.status === s.code))
        .concat(current ? [current] : [{ code: "CANCELLED", label: "Cancelled", sequence: 99, tone: "error", description: "Order was cancelled", isTerminal: true }])
    : statuses.filter((s) => !(s.isTerminal && s.tone === "error"));

  const currentSeq = current?.sequence ?? 10;

  return (
    <div className="order-tracking-timeline" style={{ padding: "4px 0" }}>
      {steps.map((step, index) => {
        const event = history.find((h) => h.status === step.code) ||
          (step.code === "PLACED" && order.placedAt
            ? { status: "PLACED", label: "Order Placed", at: order.placedAt, by: order.createdBy, note: null }
            : undefined);

        const done = !isCancelled && Boolean(event && (step.sequence < currentSeq || (step.code === "DELIVERED" && currentStatus === "DELIVERED")));
        const active = step.code === currentStatus;
        const isLast = index === steps.length - 1;

        return (
          <div
            key={step.code}
            style={{
              display: "flex",
              gap: 14,
              minHeight: isLast ? 40 : 54,
              position: "relative",
            }}
          >
            {/* Rail: Circle node + connecting vertical line */}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                width: 24,
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  zIndex: 1,
                  background: done
                    ? "var(--green-600, #16a34a)"
                    : active
                    ? isCancelled
                      ? "var(--red-600, #dc2626)"
                      : "var(--blue-600, #2563eb)"
                    : "var(--surface-muted, #f8fafc)",
                  border: done
                    ? "2px solid var(--green-600, #16a34a)"
                    : active
                    ? isCancelled
                      ? "2px solid var(--red-600, #dc2626)"
                      : "2px solid var(--blue-600, #2563eb)"
                    : "2px solid var(--border, #cbd5e1)",
                  boxShadow: active
                    ? isCancelled
                      ? "0 0 0 4px rgba(220, 38, 38, 0.15)"
                      : "0 0 0 4px rgba(37, 99, 235, 0.18)"
                    : undefined,
                  color: "#ffffff",
                  transition: "all 0.2s ease",
                }}
              >
                {done ? (
                  <Icon name="check" size={12} />
                ) : active ? (
                  isCancelled ? (
                    <Icon name="x" size={12} />
                  ) : (
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#ffffff" }} />
                  )
                ) : (
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--border-strong, #94a3b8)" }} />
                )}
              </div>
              {!isLast ? (
                <div
                  style={{
                    width: 2,
                    flex: 1,
                    margin: "4px 0",
                    background: done ? "var(--green-600, #16a34a)" : "var(--border, #e2e8f0)",
                    transition: "background 0.2s ease",
                  }}
                />
              ) : null}
            </div>

            {/* Content: Title, status pill, timestamp, by, and note */}
            <div style={{ flex: 1, paddingBottom: isLast ? 4 : 14 }}>
              <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <strong
                  style={{
                    fontSize: "0.92rem",
                    color: active || done ? "var(--text)" : "var(--text-muted)",
                    fontWeight: active ? 700 : done ? 600 : 500,
                  }}
                >
                  {step.label}
                </strong>
                {active ? (
                  <span
                    style={{
                      fontSize: "0.68rem",
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                      padding: "2px 7px",
                      borderRadius: 9999,
                      background: isCancelled ? "var(--danger-50, #fee2e2)" : "var(--blue-50, #dbeafe)",
                      color: isCancelled ? "var(--danger-700, #b91c1c)" : "var(--blue-700, #1d4ed8)",
                      border: `1px solid ${isCancelled ? "var(--danger-200, #fca5a5)" : "var(--blue-200, #bfdbfe)"}`,
                    }}
                  >
                    {isCancelled ? "Cancelled" : "Current Status"}
                  </span>
                ) : null}
              </div>

              {event?.at ? (
                <div className="text-muted text-small" style={{ marginTop: 2, fontSize: "0.82rem" }}>
                  <span>{formatDateTime(event.at)}</span>
                  {event.by ? (
                    <span>
                      {" "}· by <strong style={{ color: "var(--text)", fontWeight: 500 }}>{event.by}</strong>
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="text-muted text-small" style={{ marginTop: 2, fontSize: "0.82rem" }}>
                  {step.description || "Pending"}
                </div>
              )}

              {event?.note ? (
                <div
                  style={{
                    marginTop: 6,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 9px",
                    borderRadius: 6,
                    fontSize: "0.8rem",
                    background: "var(--surface-muted, #f8fafc)",
                    border: "1px solid var(--border, #e2e8f0)",
                    color: "var(--text-muted)",
                  }}
                >
                  <Icon name="calendar" size={12} />
                  <span>{event.note}</span>
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
export default OrderTrackingTimeline;
