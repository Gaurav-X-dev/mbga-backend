import { getLogisticsOptions } from "../../api/logistics.api";
import "../logistics/logistics.css";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { listMerchants } from "../../api/merchants.api";
import {
  cancelOrder,
  confirmOrder,
  confirmOrders,
  getOrderCutoff,
  listOrders,
  listOrderStatuses,
  type DeliveryAssignment,
  type Order,
  type OrderStatusMeta,
} from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge } from "../../components/common/StatusBadge";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatNumber,
  formatRelativeTime,
  humanize,
} from "../../utils/format";
import type { Tone } from "../../utils/labels";
import { ConfirmOrderDialog } from "./ConfirmOrderDialog";
import { CreateOrderDialog } from "./CreateOrderDialog";
import { OrderBulkActionDialog, type BulkActionChoice } from "./OrderBulkActionDialog";
import { CYLINDER_TYPES, cylinderShortLabel } from "./order-constants";
import { OrderDrawer } from "./OrderDrawer";

const PAGE_SIZE = 20;
const TRUNCATE = { display: "block", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;
const FILTERS = ["merchant", "status", "search", "priority"] as const;

const TABS = [
  { value: "ACTIVE", label: "Active" },
  { value: "PLACED", label: "Awaiting confirmation" },
  { value: "CONFIRMED", label: "Confirmed" },
  { value: "OUT_FOR_DELIVERY", label: "Out for delivery" },
  { value: "DELIVERED", label: "Delivered" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "ALL", label: "All" },
] as const;

const FALLBACK_TONE: Record<string, Tone> = {
  PLACED: "warning",
  CONFIRMED: "info",
  OUT_FOR_DELIVERY: "accent",
  ON_LOCATION: "accent",
  DELIVERED: "success",
  CANCELLED: "danger",
};

const CATALOGUE_TONE: Record<OrderStatusMeta["tone"], Tone> = {
  success: "success",
  warning: "warning",
  error: "danger",
  info: "info",
  pending: "warning",
  neutral: "neutral",
};

export function AdminOrdersPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = isMerchantPanel ? "Cylinder Orders" : "Orders"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage, reset } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000,
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const tab = values.status || "ACTIVE";

  // Cylinder filter (par with merchant app: ALL or specific cylinder code)
  const [cylinderFilter, setCylinderFilter] = useState<string>("ALL");

  const [openOrderId, setOpenOrderId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [bulkDialogAction, setBulkDialogAction] = useState<BulkActionChoice>("CONFIRM");
  const [confirmTarget, setConfirmTarget] = useState<Order[] | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Order[] | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  useEffect(() => {
    setSelected(new Set());
  }, [merchantId, tab, values.search, cylinderFilter]);

  const priorityOptions=useQuery({queryKey:["logistics","options",merchantId],queryFn:({signal})=>getLogisticsOptions({merchant:isMerchantPanel,merchantId},signal),enabled:Boolean(merchantId),retry:false});
  const params = { merchantId, status: tab, search: values.search || undefined, priorityCode:values.priority || undefined };
  const query = useQuery({
    queryKey: queryKeys.orders.list(params),
    queryFn: ({ signal }) => listOrders(params, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData,
  });

  const allParams = { merchantId, status: "ALL" };
  const allOrders = useQuery({
    queryKey: queryKeys.orders.list(allParams),
    queryFn: ({ signal }) => listOrders(allParams, signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000,
  });

  const statuses = useQuery({
    queryKey: queryKeys.orders.statuses(merchantId),
    queryFn: ({ signal }) => listOrderStatuses(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 10 * 60_000,
    retry: false,
  });

  const cutoff = useQuery({
    queryKey: queryKeys.orders.cutoff(merchantId),
    queryFn: ({ signal }) => getOrderCutoff(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 60_000,
    retry: false,
  });

  const statusLookup = useMemo(
    () => new Map((statuses.data ?? []).map((item) => [item.code as string, item])),
    [statuses.data]
  );

  function renderStatus(status: string) {
    const meta = statusLookup.get(status);
    const tone = meta ? CATALOGUE_TONE[meta.tone] : (FALLBACK_TONE[status] ?? "neutral");
    return <Badge tone={tone}>{meta?.label ?? humanize(status)}</Badge>;
  }

  const counts = useMemo(() => {
    const rows = allOrders.data ?? [];
    const by = (status: string) => rows.filter((order) => order.status === status).length;
    return {
      all: rows.length,
      active: rows.filter((order) => order.status !== "DELIVERED" && order.status !== "CANCELLED").length,
      placed: by("PLACED"),
      confirmed: by("CONFIRMED"),
      dispatched: by("OUT_FOR_DELIVERY") + by("ON_LOCATION"),
      delivered: by("DELIVERED"),
      cancelled: by("CANCELLED"),
      inTransit: by("CONFIRMED") + by("OUT_FOR_DELIVERY") + by("ON_LOCATION"),
      value: rows.filter((order) => order.status !== "CANCELLED").reduce((sum, order) => sum + order.totalAmount, 0),
    };
  }, [allOrders.data]);

  // Filter rows by cylinder selection (par with merchant app)
  const filteredRows = useMemo(() => {
    const rows = query.data ?? [];
    if (cylinderFilter === "ALL") return rows;
    const short = cylinderShortLabel(cylinderFilter);
    return rows.filter((o) => {
      if (o.itemsSummary && (o.itemsSummary.includes(short) || o.itemsSummary.includes(cylinderFilter))) return true;
      if (o.items?.some((it) => it.cylinderType === cylinderFilter || it.cylinderLabel?.includes(short))) return true;
      return false;
    });
  }, [query.data, cylinderFilter]);

  const pageRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // An order is selectable if in PLACED state or can be cancelled
  const selectable = (order: Order) => order.status === "PLACED" || order.canCancel !== false;
  const selectableOnPage = pageRows.filter(selectable);
  const allOnPageSelected = selectableOnPage.length > 0 && selectableOnPage.every((order) => selected.has(order.id));
  const someOnPageSelected = selectableOnPage.some((order) => selected.has(order.id)) && !allOnPageSelected;

  function toggleSelectAllOnPage() {
    setSelected((previous) => {
      const next = new Set(previous);
      if (allOnPageSelected) {
        selectableOnPage.forEach((order) => next.delete(order.id));
      } else {
        selectableOnPage.forEach((order) => next.add(order.id));
      }
      return next;
    });
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.deliveries.all });
  }

  const confirmMutation = useMutation({
    mutationFn: ({ orders, delivery }: { orders: Order[]; delivery: DeliveryAssignment }) => {
      const ids = orders.map((o) => o.id);
      return ids.length === 1
        ? confirmOrder(merchantId, ids[0], delivery).then(() => 1)
        : confirmOrders(merchantId, ids, delivery).then((r) => r.confirmed);
    },
    onSuccess: (confirmed) => {
      toast.success(confirmed === 1 ? "Order confirmed and delivery scheduled." : `${confirmed} orders confirmed on delivery van.`);
      setSelected(new Set());
      setConfirmTarget(null);
      invalidate();
    },
  });

  const selectedOrders = useMemo(
    () => (query.data ?? []).filter((o) => selected.has(o.id)),
    [query.data, selected]
  );

  const merchantName = merchants.data?.items.find((merchant) => merchant.id === merchantId)?.business_name;

  const columns: Column<Order>[] = [
    {key:"priority",header:"Priority",render:order=>{const p=priorityOptions.data?.policy.priorities.find(p=>p.code===order.priorityCode);return p?<span className="logistics-priority" style={{borderColor:p.color,color:"var(--text)"}}>{p.label}</span>:order.priorityCode || "—";}},
    {
      key: "select",
      header: <span className="sr-only">Select</span>,
      width: "52px",
      hideOnMobile: true,
      render: (order) =>
        selectable(order) ? (
          <button
            type="button"
            className="table-checkbox-btn"
            aria-label={`Select ${order.orderNumber}`}
            onClick={(event) => {
              event.stopPropagation();
              toggle(order.id);
            }}
          >
            <span className={`select-box select-circle ${selected.has(order.id) ? "is-selected" : ""}`}>
              {selected.has(order.id) ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="2.5 6 5 8.5 9.5 3.5" />
                </svg>
              ) : null}
            </span>
          </button>
        ) : null,
    },
    {
      key: "order",
      header: "Order",
      primary: true,
      sortValue: (order) => order.placedAt,
      render: (order) => (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          {selectable(order) ? (
            <button
              type="button"
              className="table-checkbox-btn mobile-only-select"
              style={{ marginTop: 2 }}
              aria-label={`Select ${order.orderNumber}`}
              onClick={(event) => {
                event.stopPropagation();
                toggle(order.id);
              }}
            >
              <span className={`select-box select-circle ${selected.has(order.id) ? "is-selected" : ""}`}>
                {selected.has(order.id) ? (
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="2.5 6 5 8.5 9.5 3.5" />
                  </svg>
                ) : null}
              </span>
            </button>
          ) : null}
          <div className="cell-stack">
            <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setOpenOrderId(order.id)}>
              {order.orderNumber}
            </button>
            <small className="nowrap" title={formatDateTime(order.placedAt)}>
              {formatDate(order.placedAt)} · {formatRelativeTime(order.placedAt)}
              {order.orderMode === "REPEAT" ? " · Repeat" : ""}
            </small>
          </div>
        </div>
      ),
    },
    {
      key: "customer",
      header: "Customer",
      sortValue: (order) => order.customerName,
      render: (order) => (
        <div className="cell-stack">
          <span style={TRUNCATE} title={order.customerName}>
            {order.customerName}
          </span>
          <small style={TRUNCATE}>
            {humanize(order.customerType)} · {order.deliverySiteName}
          </small>
        </div>
      ),
    },
    {
      key: "items",
      header: "Items",
      render: (order) => (
        <div className="cell-stack">
          <span style={TRUNCATE} title={order.itemsSummary}>
            {order.itemsSummary}
          </span>
          <small className="nowrap">{formatNumber(order.totalCylinders)} cylinders</small>
        </div>
      ),
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      sortValue: (order) => order.totalAmount,
      render: (order) => <strong className="nowrap">{formatCurrency(order.totalAmount)}</strong>,
    },
    {
      key: "status",
      header: "Status",
      sortValue: (order) => order.status,
      render: (order) => renderStatus(order.status),
    },
  ];

  return (
    <div className="page admin-orders-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Track, confirm and dispatch cylinder orders for your agency." : "Track, confirm and dispatch cylinder orders for each merchant."}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => {
                    setOpenOrderId(null);
                    setFilter("merchant", event.target.value);
                  }}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({
                    value: merchant.id,
                    label: merchant.business_name,
                  }))}
                />
              </Field>
            ) : null}
            <Button
              variant="secondary"
              icon="refresh"
              onClick={() => invalidate()}
              disabled={!merchantId || query.isFetching}
            >
              Refresh
            </Button>
            <Button icon="plus" onClick={() => setCreating(true)} disabled={!merchantId}>
              New order
            </Button>
          </>
        }
      />

      {merchants.error ? (
        <InlineError
          error={merchants.error}
          title="Merchants could not be loaded"
          onRetry={() => void merchants.refetch()}
        />
      ) : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState
              icon="store"
              title="Choose a merchant"
              description="Orders are kept per merchant. Pick one above to see its orders."
            />
          </Card>
        )
      ) : (
        <>
          {cutoff.data ? (
            <Alert
              tone={cutoff.data.withinCutoff ? "info" : "warning"}
              title={`Order cut-off ${cutoff.data.cutoffTime} IST`}
            >
              {cutoff.data.message} Next delivery date: {formatDate(cutoff.data.scheduledDeliveryDate)}.
            </Alert>
          ) : null}

          {/* KPI Strip */}
          <div className="kpi-grid" aria-label="Order summary">
            <StatCard
              label="Awaiting confirmation"
              icon="clock"
              tone="amber"
              value={formatNumber(allOrders.data ? counts.placed : undefined)}
              hint="Placed, no van assigned yet"
            />
            <StatCard
              label="In progress"
              icon="truck"
              tone="blue"
              value={formatNumber(allOrders.data ? counts.inTransit : undefined)}
              hint="Confirmed or on the road"
            />
            <StatCard
              label="Delivered"
              icon="checkCircle"
              tone="green"
              value={formatNumber(allOrders.data ? counts.delivered : undefined)}
              hint="Completed orders"
            />
            <StatCard
              label="Order value"
              icon="wallet"
              tone="violet"
              value={allOrders.data ? formatCurrency(counts.value) : "—"}
              hint="Excluding cancelled, GST incl."
            />
          </div>

          <Card bodyless className="table-card">
            {/* 1. Status Tabs */}
            <div className="status-tabs status-tabs--card" role="tablist" aria-label="Order status">
              {TABS.map((item) => {
                const count =
                  item.value === "ALL"
                    ? counts.all
                    : item.value === "ACTIVE"
                    ? counts.active
                    : item.value === "PLACED"
                    ? counts.placed
                    : item.value === "CONFIRMED"
                    ? counts.confirmed
                    : item.value === "OUT_FOR_DELIVERY"
                    ? counts.dispatched
                    : item.value === "DELIVERED"
                    ? counts.delivered
                    : counts.cancelled;
                return (
                  <button
                    key={item.value}
                    type="button"
                    role="tab"
                    aria-selected={tab === item.value}
                    onClick={() => setFilter("status", item.value)}
                  >
                    {item.label}
                    {allOrders.data && count > 0 ? (
                      <span className="tab-count">{count}</span>
                    ) : null}
                  </button>
                );
              })}
            </div>

            {/* 2. Cylinder Filter Chips (Merchant App Parity) */}
            <div className="cylinder-chips-bar" role="toolbar" aria-label="Filter by cylinder size">
              <span className="cylinder-chips-label">Size:</span>
              <button
                type="button"
                className={`cylinder-chip ${cylinderFilter === "ALL" ? "is-active" : ""}`}
                onClick={() => setCylinderFilter("ALL")}
              >
                All cylinders
              </button>
              {CYLINDER_TYPES.map((c) => (
                <button
                  key={c.code}
                  type="button"
                  className={`cylinder-chip ${cylinderFilter === c.code ? "is-active" : ""}`}
                  onClick={() => setCylinderFilter(c.code)}
                >
                  <Icon name="flame" size={13} />
                  <span>{c.shortLabel}</span>
                </button>
              ))}
            </div>

            {/* 3. Search & Filter Bar */}
            <FilterBar
              onReset={() => {
                reset();
                setCylinderFilter("ALL");
              }}
              canReset={Boolean(values.priority || values.search || cylinderFilter !== "ALL")}
              actions={
                <span className="text-muted text-small nowrap">
                  {filteredRows.length} {filteredRows.length === 1 ? "order" : "orders"}
                  {merchantName ? ` · ${merchantName}` : ""}
                </span>
              }
            >
              <SearchInput
                label="Search orders"
                placeholder="Search by order number, customer, site or cylinder"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
              />
              <Field label="Priority"><Select value={values.priority} placeholder="All priorities" options={(priorityOptions.data?.policy.priorities || []).map(p=>({value:p.code,label:p.label}))} onChange={e=>setFilter("priority",e.target.value)}/></Field>
            </FilterBar>

            {/* 4. Select All Bar (Parity with Merchant App Screenshot) */}
            <div className={`orders-select-bar ${selected.size > 0 ? "is-active" : ""}`}>
              <button
                type="button"
                className="orders-select-all-btn"
                onClick={toggleSelectAllOnPage}
                aria-checked={allOnPageSelected ? "true" : someOnPageSelected ? "mixed" : "false"}
                role="checkbox"
              >
                <span
                  className={`select-box select-circle ${allOnPageSelected ? "is-selected" : someOnPageSelected ? "is-indeterminate" : ""}`}
                >
                  {allOnPageSelected ? (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <polyline points="2.5 6 5 8.5 9.5 3.5" />
                    </svg>
                  ) : someOnPageSelected ? (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
                      <line x1="2.5" y1="6" x2="9.5" y2="6" />
                    </svg>
                  ) : null}
                </span>
                <span>{allOnPageSelected ? "Deselect all" : "Select all"}</span>
              </button>

              <div className="row" style={{ gap: 8, alignItems: "center" }}>
                {selected.size > 0 ? (
                  <>
                    <span className="badge badge--info" style={{ fontWeight: 600 }}>
                      {selected.size} {selected.size === 1 ? "order" : "orders"} selected
                    </span>
                    <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
                      Clear
                    </Button>
                    <Button
                      size="sm"
                      icon="zap"
                      onClick={() => {
                        setBulkDialogAction("CONFIRM");
                        setBulkDialogOpen(true);
                      }}
                    >
                      Bulk action
                    </Button>
                  </>
                ) : (
                  <span className="text-muted text-small">
                    {selectableOnPage.length} order{selectableOnPage.length === 1 ? "" : "s"} on page
                  </span>
                )}
              </div>
            </div>

            {query.error && query.data ? (
              <div style={{ padding: "var(--space-4)" }}>
                <InlineError
                  error={query.error}
                  title="The list could not be refreshed"
                  onRetry={() => void query.refetch()}
                />
              </div>
            ) : null}

            <DataTable
              caption="Orders"
              columns={columns}
              rows={query.data ? pageRows : undefined}
              getRowKey={(order) => order.id}
              onRowClick={(order) => setOpenOrderId(order.id)}
              rowLabel={(order) => order.orderNumber}
              isSelected={(order) => selected.has(order.id)}
              rowActions={(order) => [
                { label: "View details", icon: "eye", onSelect: () => setOpenOrderId(order.id) },
                ...(order.status === "PLACED"
                  ? [
                      {
                        label: "Confirm & assign",
                        icon: "truck" as const,
                        onSelect: () => setConfirmTarget([order]),
                      },
                    ]
                  : []),
                ...(order.canCancel
                  ? [
                      {
                        label: "Cancel order",
                        icon: "ban" as const,
                        danger: true,
                        onSelect: () => setCancelTarget([order]),
                      },
                    ]
                  : []),
              ]}
              isLoading={query.isLoading}
              error={query.data ? undefined : query.error}
              onRetry={() => void query.refetch()}
              empty={
                values.search || cylinderFilter !== "ALL" ? (
                  <EmptyState
                    icon="search"
                    title="No orders match your filter"
                    description="Try selecting 'All cylinders' or a different search term."
                    action={
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setFilter("search", "");
                          setCylinderFilter("ALL");
                        }}
                      >
                        Reset filters
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    icon="cart"
                    title="No orders here"
                    description="Orders in this status will appear here."
                    action={<Button icon="plus" onClick={() => setCreating(true)}>New order</Button>}
                  />
                )
              }
              footer={
                <Pagination
                  page={page}
                  pageSize={PAGE_SIZE}
                  total={filteredRows.length}
                  onPageChange={setPage}
                  itemLabel="orders"
                  disabled={query.isFetching}
                />
              }
            />
          </Card>
        </>
      )}


      {/* Bulk Action Dialog (Full parity with Merchant App OrderBulkActionSheet) */}
      {bulkDialogOpen && merchantId && selectedOrders.length > 0 ? (
        <OrderBulkActionDialog
          open={bulkDialogOpen}
          merchantId={merchantId}
          orders={selectedOrders}
          initialAction={bulkDialogAction}
          onClose={() => setBulkDialogOpen(false)}
          onSuccess={() => {
            setSelected(new Set());
            invalidate();
          }}
        />
      ) : null}

      {/* 4. Order Details Drawer */}
      {openOrderId && merchantId ? (
        <OrderDrawer
          merchantId={merchantId}
          orderId={openOrderId}
          onClose={() => setOpenOrderId(null)}
          renderStatus={renderStatus}
          onConfirm={() => {
            const current = (query.data ?? []).find((o) => o.id === openOrderId);
            if (current) setConfirmTarget([current]);
          }}
          onCancel={(order) => setCancelTarget([order])}
        />
      ) : null}

      {/* 5. Create Order Dialog */}
      {merchantId ? (
        <CreateOrderDialog
          open={creating}
          merchantId={merchantId}
          onClose={() => setCreating(false)}
          onCreated={(order) => {
            invalidate();
          }}
        />
      ) : null}

      {/* 6. Confirm & Schedule Delivery Dialog (Single or Bulk) */}
      {confirmTarget && merchantId ? (
        <ConfirmOrderDialog
          open={confirmTarget !== null}
          merchantId={merchantId}
          orders={confirmTarget}
          pending={confirmMutation.isPending}
          error={confirmMutation.error}
          onClose={() => {
            confirmMutation.reset();
            setConfirmTarget(null);
          }}
          onSubmit={(delivery) =>
            confirmTarget && confirmMutation.mutate({ orders: confirmTarget, delivery })
          }
        />
      ) : null}

      {/* 7. Cancel Order Dialog (Single or Bulk) */}
      <CancelOrderDialog
        orders={cancelTarget}
        onClose={() => setCancelTarget(null)}
        onConfirm={async (reason) => {
          if (!cancelTarget || !cancelTarget.length) return;
          for (const ord of cancelTarget) {
            await cancelOrder(merchantId, ord.id, reason);
          }
          toast.success(
            cancelTarget.length === 1
              ? `${cancelTarget[0].orderNumber} was cancelled.`
              : `${cancelTarget.length} orders were cancelled.`
          );
          setSelected(new Set());
          setCancelTarget(null);
          invalidate();
        }}
      />
    </div>
  );
}

function CancelOrderDialog({
  orders,
  onClose,
  onConfirm,
}: {
  orders: Order[] | null;
  onClose: () => void;
  onConfirm: (reason?: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [orders]);

  const count = orders?.length ?? 0;
  const title = count > 1 ? `Cancel ${count} orders?` : "Cancel this order?";
  const description =
    count > 1
      ? `All ${count} selected orders will be cancelled. This action cannot be undone.`
      : orders?.[0]
        ? `${orders[0].orderNumber} for ${orders[0].customerName} (${formatCurrency(orders[0].totalAmount)}) will be cancelled. This cannot be undone.`
        : "";

  return (
    <ConfirmationDialog
      open={orders !== null && orders.length > 0}
      title={title}
      description={description}
      confirmLabel={count > 1 ? `Cancel ${count} orders` : "Cancel order"}
      onClose={onClose}
      onConfirm={() => onConfirm(reason.trim() || undefined)}
    >
      <Field label="Cancellation reason" required>
        <Textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={255}
          rows={3}
          placeholder="e.g. Customer requested cancellation / duplicate order"
          autoFocus
        />
      </Field>
    </ConfirmationDialog>
  );
}

export default AdminOrdersPage;
