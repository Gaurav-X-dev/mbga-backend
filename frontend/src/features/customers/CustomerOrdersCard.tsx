import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listOrders, type Order } from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Card, MiniStat } from "../../components/layout/Page";
import { formatCurrency, formatDate, formatNumber, formatRelativeTime, humanize } from "../../utils/format";
import type { Tone } from "../../utils/labels";

const STATUS_TONE: Record<string, Tone> = {
  PLACED: "warning",
  CONFIRMED: "info",
  OUT_FOR_DELIVERY: "accent",
  ON_LOCATION: "accent",
  DELIVERED: "success",
  CANCELLED: "danger"
};

const SHOWN = 10;

/** The customer's order history, read through the merchant-scoped orders API. */
export function CustomerOrdersCard({ merchantId, customerId }: { merchantId: string | null; customerId: string | null }) {
  const auth = useAuth();
  const allowed = auth.can(PERMISSIONS.ordersView);
  const params = { merchantId: merchantId ?? "", customerId: customerId ?? "", status: "ALL" };
  const query = useQuery({
    queryKey: queryKeys.orders.list(params),
    queryFn: ({ signal }) => listOrders(params, signal),
    enabled: allowed && Boolean(merchantId && customerId)
  });

  if (!allowed) return null;

  const orders = query.data ?? [];
  const live = orders.filter((order) => order.status !== "CANCELLED");
  const ordersHref = (order?: Order) =>
    `${auth.channel === "merchant" ? "/merchant" : "/admin"}/orders?merchant=${encodeURIComponent(merchantId ?? "")}&status=ALL${order ? `&search=${encodeURIComponent(order.orderNumber)}` : ""}`;

  return (
    <Card
      title="Orders"
      subtitle="Everything this customer has ordered"
      actions={
        orders.length > SHOWN ? (
          <ButtonLink to={ordersHref()} variant="link" size="sm">
            View all
          </ButtonLink>
        ) : null
      }
    >
      {!merchantId || !customerId ? (
        <EmptyState icon="cart" title="Orders unavailable" description="This application is not linked to a merchant yet, so there are no orders to show." />
      ) : query.isLoading ? (
        <LoadingSkeleton rows={4} label="Loading orders" />
      ) : query.error ? (
        <InlineError error={query.error} title="Orders could not be loaded" onRetry={() => void query.refetch()} />
      ) : !orders.length ? (
        <EmptyState icon="cart" title="No orders yet" description="Orders appear here once the customer is approved and places one." />
      ) : (
        <div className="stack">
          <div className="mini-stat-strip row" style={{ gap: "var(--space-4)" }}>
            <MiniStat label="Orders" value={formatNumber(orders.length)} icon="cart" />
            <MiniStat label="Delivered" value={formatNumber(orders.filter((o) => o.status === "DELIVERED").length)} icon="checkCircle" tone="green" />
            <MiniStat label="Total value" value={formatCurrency(live.reduce((sum, o) => sum + o.totalAmount, 0))} icon="wallet" tone="violet" />
            <MiniStat label="Last order" value={formatRelativeTime(orders[0].placedAt)} icon="clock" tone="amber" />
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <caption className="sr-only">Customer orders</caption>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Items</th>
                  <th style={{ textAlign: "right" }}>Amount</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, SHOWN).map((order) => (
                  <tr key={order.id}>
                    <td>
                      <div className="cell-stack">
                        <Link to={ordersHref(order)} className="cell-primary__title nowrap">
                          {order.orderNumber}
                        </Link>
                        <small className="nowrap">{formatDate(order.placedAt)}</small>
                      </div>
                    </td>
                    <td>
                      <span
                        title={order.itemsSummary}
                        style={{ display: "block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      >
                        {order.itemsSummary}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <strong className="nowrap">{formatCurrency(order.totalAmount)}</strong>
                    </td>
                    <td>
                      <Badge tone={STATUS_TONE[order.status] ?? "neutral"}>{humanize(order.status)}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
