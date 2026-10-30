import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listDeliveryMembers } from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator, Skeleton } from "../../components/feedback/Feedback";
import { Card, PageHeader, SectionHeader, StatCard } from "../../components/layout/Page";
import { DataTable, TableHeader, type Column } from "../../components/tables/DataTable";
import { formatCurrency, formatDateTime, formatNumber, formatRelativeTime, humanize } from "../../utils/format";
import type { Tone } from "../../utils/labels";

const STALE = 60_000;

function useTeamCount(filters: { delivery_user_type?: string; status?: string }, enabled: boolean) {
  const params = { ...filters, limit: 1, offset: 0 };
  return useQuery({
    queryKey: queryKeys.deliveryTeam.list(params),
    queryFn: ({ signal }) => listDeliveryMembers(params, signal),
    select: (data) => data.total,
    enabled,
    staleTime: STALE
  });
}

interface RecentOrderRow {
  id: string;
  number: string;
  customer: string;
  type: string;
  items: string;
  amount: number;
  status: string;
  time: string;
}

const RECENT_ORDERS: RecentOrderRow[] = [
  { id: "ord-m1", number: "ORD-2610-0284", customer: "Annapurna Sweets & Caters", type: "COMMERCIAL", items: "4 × 19 KG Commercial", amount: 8496, status: "OUT_FOR_DELIVERY", time: "10 mins ago" },
  { id: "ord-m2", number: "ORD-2610-0283", customer: "Apex Precision Castings", type: "INDUSTRIAL", items: "2 × 47.5 KG L-Offtake", amount: 16800, status: "CONFIRMED", time: "35 mins ago" },
  { id: "ord-m3", number: "ORD-2610-0282", customer: "Golden Palace Restaurant", type: "RETAIL", items: "2 × 19 KG Commercial", amount: 4248, status: "DELIVERED", time: "1 hour ago" },
  { id: "ord-m4", number: "ORD-2610-0281", customer: "Royal Bakers & Confectionery", type: "RETAIL", items: "3 × 19 KG Commercial", amount: 6372, status: "DELIVERED", time: "2 hours ago" },
  { id: "ord-m5", number: "ORD-2610-0280", customer: "Vikas Engineering Works", type: "INDUSTRIAL", items: "1 × 422 KG Hippo", amount: 48900, status: "PLACED", time: "3 hours ago" }
];

const INVENTORY_SUMMARY = [
  { type: "19 KG Commercial", filled: 84, empty: 32, damaged: 2, total: 118, tone: "success" as Tone },
  { type: "47.5 KG Liquid (L)", filled: 28, empty: 14, damaged: 0, total: 42, tone: "success" as Tone },
  { type: "47.5 KG Vapour (V)", filled: 18, empty: 6, damaged: 1, total: 25, tone: "warning" as Tone },
  { type: "422 KG Hippo", filled: 4, empty: 2, damaged: 0, total: 6, tone: "success" as Tone },
  { type: "5 KG / 10 KG FTL", filled: 45, empty: 12, damaged: 0, total: 57, tone: "success" as Tone }
];

const ORDER_TONE: Record<string, Tone> = {
  PLACED: "warning",
  CONFIRMED: "info",
  OUT_FOR_DELIVERY: "accent",
  DELIVERED: "success",
  CANCELLED: "danger"
};

export function MerchantDashboardPage() {
  const auth = useAuth();
  const canTeam = auth.can(PERMISSIONS.deliveryUsersView);
  const total = useTeamCount({}, canTeam);
  const activeDrivers = useTeamCount({ delivery_user_type: "DRIVER", status: "ACTIVE" }, canTeam);
  const activeHelpers = useTeamCount({ delivery_user_type: "HELPER", status: "ACTIVE" }, canTeam);
  const blocked = useTeamCount({ status: "BLOCKED" }, canTeam);

  const countError = total.error ?? activeDrivers.error ?? activeHelpers.error ?? blocked.error;
  const firstName = auth.user?.display_name?.split(" ")[0];
  const merchantName = (auth.user?.merchant as any)?.business_name || (auth.user?.merchant as any)?.name || "Madhav Bharat Gas Agency";

  const value = (query: { data?: number; isLoading: boolean }) =>
    query.isLoading ? <Skeleton width={56} height={32} /> : formatNumber(query.data);

  const orderColumns: Column<RecentOrderRow>[] = [
    {
      key: "number",
      header: "Order #",
      primary: true,
      render: (ord) => (
        <div className="cell-primary">
          <div className="cell-primary__text">
            <Link to="/merchant/orders" className="cell-primary__title nowrap mono">
              {ord.number}
            </Link>
            <span className="cell-primary__subtitle nowrap">{ord.time}</span>
          </div>
        </div>
      )
    },
    {
      key: "customer",
      header: "Customer",
      render: (ord) => (
        <div className="cell-stack">
          <strong>{ord.customer}</strong>
          <small className="text-muted">{humanize(ord.type)}</small>
        </div>
      )
    },
    {
      key: "items",
      header: "Items",
      render: (ord) => <span className="nowrap">{ord.items}</span>
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      render: (ord) => <strong>{formatCurrency(ord.amount)}</strong>
    },
    {
      key: "status",
      header: "Status",
      render: (ord) => (
        <Badge tone={ORDER_TONE[ord.status] ?? "neutral"}>
          {humanize(ord.status)}
        </Badge>
      )
    }
  ];

  return (
    <div className="page dashboard-page">
      <PageHeader
        title="Dashboard"
        documentTitle="Dashboard"
        description={firstName ? `Welcome back, ${firstName}. Agency operations overview for ${merchantName}.` : `Agency operations overview for ${merchantName}.`}
        meta={<RefreshIndicator active={total.isFetching && !total.isLoading} />}
        actions={
          <div className="dashboard-actions">
            <ButtonLink to="/merchant/orders?create=1" variant="primary" icon="plus">
              Create Order
            </ButtonLink>
            <ButtonLink to="/merchant/customers?create=1" variant="secondary" icon="userPlus">
              Add Customer
            </ButtonLink>
            {auth.can(PERMISSIONS.deliveryUsersCreate) ? (
              <ButtonLink to="/merchant/delivery-team/new" variant="secondary" icon="truck">
                Add Team Member
              </ButtonLink>
            ) : null}
          </div>
        }
      />

      {/* OPERATIONS KPI STATS MATCHING ADMIN DASHBOARD */}
      <section className="stack" aria-labelledby="operations-heading">
        <SectionHeader
          id="operations-heading"
          title="Operations Health"
          description="Core operating signals across cylinder orders, inventory, cashflow, and customer network."
        />
        <div className="kpi-grid">
          <StatCard
            label="Active Orders Today"
            icon="cart"
            tone="blue"
            value="18"
            to="/merchant/orders"
            linkLabel="View orders"
            hint="5 awaiting dispatch"
          />
          <StatCard
            label="Filled Commercial Stock"
            icon="box"
            tone="green"
            value="179"
            to="/merchant/inventory"
            linkLabel="View stock"
            hint="84 × 19KG · 46 × 47.5KG"
          />
          <StatCard
            label="Today's Collections"
            icon="wallet"
            tone="violet"
            value="₹42,500"
            to="/merchant/payments"
            linkLabel="View payments"
            hint="9 invoices settled"
          />
          <StatCard
            label="Customer Accounts"
            icon="users"
            tone="blue"
            value="48"
            to="/merchant/customers"
            linkLabel="View customers"
            hint="32 retail · 16 industrial"
          />
        </div>
      </section>

      {/* DELIVERY FLEET SECTION MATCHING ADMIN */}
      {canTeam ? (
        <section className="stack" aria-labelledby="team-heading">
          <SectionHeader
            id="team-heading"
            title="Delivery Fleet & Field Team"
            description="Active drivers, helpers, and van dispatches on the road."
            actions={
              <Link to="/merchant/delivery-team" className="text-small">
                Manage team →
              </Link>
            }
          />
          {countError && total.data === undefined ? (
            <InlineError
              error={countError}
              title="Team figures could not be loaded"
              onRetry={() => {
                void total.refetch();
                void activeDrivers.refetch();
                void activeHelpers.refetch();
                void blocked.refetch();
              }}
            />
          ) : (
            <div className="kpi-grid">
              <StatCard
                label="Total Team"
                icon="users"
                tone="blue"
                value={value(total)}
                to="/merchant/delivery-team"
                linkLabel="View team"
                hint="Registered delivery personnel"
              />
              <StatCard
                label="Active Drivers"
                icon="truck"
                tone="green"
                value={value(activeDrivers)}
                to="/merchant/delivery-team?type=DRIVER&status=ACTIVE"
                linkLabel="View drivers"
                hint="Assigned to delivery vans"
              />
              <StatCard
                label="Active Helpers"
                icon="user"
                tone="blue"
                value={value(activeHelpers)}
                to="/merchant/delivery-team?type=HELPER&status=ACTIVE"
                linkLabel="View helpers"
                hint="Cylinder loading & transport"
              />
              <StatCard
                label="Blocked Accounts"
                icon="ban"
                tone="red"
                value={value(blocked)}
                to="/merchant/delivery-team?status=BLOCKED"
                linkLabel="View blocked"
                hint="Access suspended"
              />
            </div>
          )}
        </section>
      ) : null}

      {/* RECENT ORDERS TABLE MATCHING ADMIN TABLE CARD */}
      <Card bodyless className="table-card">
        <TableHeader
          title="Recent Cylinder Orders"
          count={RECENT_ORDERS.length}
          description="Latest commercial and retail cylinder orders placed today."
          actions={
            <Link to="/merchant/orders" className="text-small">
              View all orders →
            </Link>
          }
        />
        <DataTable
          caption="Recent Orders"
          columns={orderColumns}
          rows={RECENT_ORDERS}
          getRowKey={(ord) => ord.id}
          rowLabel={(ord) => ord.number}
          empty={
            <EmptyState
              icon="cart"
              title="No recent orders"
              description="Orders placed today will appear here."
            />
          }
        />
      </Card>

      {/* GODOWN INVENTORY SNAPSHOT */}
      <section className="stack">
        <SectionHeader
          title="Godown Cylinder Inventory Snapshot"
          description="Live filled and empty balance per cylinder size."
          actions={
            <Link to="/merchant/inventory" className="text-small">
              Manage inventory →
            </Link>
          }
        />
        <div className="grid-3" style={{ gap: "var(--space-4)" }}>
          {INVENTORY_SUMMARY.map((cyl, i) => (
            <div
              key={i}
              className="card"
              style={{ borderRadius: "var(--radius-md)" }}
            >
              <div className="card__body" style={{ padding: "var(--space-4)" }}>
                <div className="row" style={{ justifyContent: "space-between", marginBottom: "var(--space-2)" }}>
                  <h3 style={{ fontSize: "15px", fontWeight: 600, margin: 0 }}>{cyl.type}</h3>
                  <Badge tone={cyl.tone}>{cyl.tone === "success" ? "Optimal" : "Low Stock"}</Badge>
                </div>
                <div className="row" style={{ justifyContent: "space-between", fontSize: "14px", marginTop: "var(--space-3)" }}>
                  <span className="meta">Filled cylinders:</span>
                  <strong style={{ color: "var(--green-600, #10b981)" }}>{cyl.filled}</strong>
                </div>
                <div className="row" style={{ justifyContent: "space-between", fontSize: "14px", marginTop: "var(--space-1)" }}>
                  <span className="meta">Empty cylinders:</span>
                  <strong style={{ color: "var(--blue-600, #3b82f6)" }}>{cyl.empty}</strong>
                </div>
                <div className="row" style={{ justifyContent: "space-between", fontSize: "14px", marginTop: "var(--space-1)" }}>
                  <span className="meta">Total in stock:</span>
                  <strong>{cyl.total}</strong>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default MerchantDashboardPage;
