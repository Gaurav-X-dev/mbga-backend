import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getDelivery, listDeliveries, reassignDelivery, type DeliverySlip, type DeliveryStatus, type ReassignDeliveryInput } from "../../api/deliveries.api";
import { normalizeError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import type { Address } from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { listDeliveryEligibleVehicles } from "../../api/vehicles.api";
import { EligibleVehicleField } from "../admin-vehicles/EligibleVehicleField";
import { ButtonLink, Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatDate, formatDateTime, formatNumber, formatRelativeTime, todayInputValue } from "../../utils/format";
import type { Tone } from "../../utils/labels";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "status", "search"] as const;

const STATUS_META: Record<DeliveryStatus, { label: string; tone: Tone }> = {
  SCHEDULED: { label: "Scheduled", tone: "info" },
  DISPATCHED: { label: "Dispatched", tone: "accent" },
  ON_LOCATION: { label: "At customer", tone: "warning" },
  DELIVERED: { label: "Delivered", tone: "success" },
  FAILED: { label: "Failed", tone: "danger" }
};

const TABS: Array<{ value: string; label: string }> = [
  { value: "ALL", label: "All" },
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "DISPATCHED", label: "Dispatched" },
  { value: "ON_LOCATION", label: "At customer" },
  { value: "DELIVERED", label: "Delivered" },
  { value: "FAILED", label: "Failed" }
];

const TRUNCATE = { display: "block", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;

function DeliveryStatusBadge({ status }: { status: DeliveryStatus }) {
  const meta = STATUS_META[status] ?? { label: status, tone: "neutral" as Tone };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

function formatAddress(address: Address | null | undefined) {
  if (!address) return "—";
  return [address.line1, address.line2, address.city, address.state, address.pincode].filter(Boolean).join(", ") || "—";
}

export function AdminDeliveriesPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = "Deliveries"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const tab = values.status || "ALL";
  const [openId, setOpenId] = useState<string | null>(null);
  const [reassigning, setReassigning] = useState<DeliverySlip | null>(null);

  // Slips are kept per merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  const params = { merchantId, status: tab, search: values.search || undefined };
  const query = useQuery({
    queryKey: queryKeys.deliveries.list(params),
    queryFn: ({ signal }) => listDeliveries(params, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData,
    // The dispatch board changes as drivers move; keep it reasonably fresh.
    refetchInterval: 60_000
  });
  const allParams = { merchantId, status: "ALL" };
  const all = useQuery({
    queryKey: queryKeys.deliveries.list(allParams),
    queryFn: ({ signal }) => listDeliveries(allParams, signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000
  });

  const counts = useMemo(() => {
    const rows = all.data ?? [];
    const by = (status: DeliveryStatus) => rows.filter((slip) => slip.status === status).length;
    return {
      SCHEDULED: by("SCHEDULED"),
      DISPATCHED: by("DISPATCHED"),
      ON_LOCATION: by("ON_LOCATION"),
      DELIVERED: by("DELIVERED"),
      FAILED: by("FAILED"),
      pendingPickup: rows.reduce((sum, slip) => sum + (slip.pendingPickup ?? 0), 0)
    } as Record<string, number>;
  }, [all.data]);

  const rows = query.data ?? [];
  const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const ready = Boolean(all.data);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.deliveries.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
  }

  const columns: Column<DeliverySlip>[] = [
    {
      key: "slip",
      header: "Slip",
      primary: true,
      sortValue: (slip) => slip.slipNumber,
      render: (slip) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setOpenId(slip.id)}>
            {slip.slipNumber}
          </button>
          <small className="nowrap">{slip.orderNumber}</small>
        </div>
      )
    },
    {
      key: "customer",
      header: "Customer",
      sortValue: (slip) => slip.customerName,
      render: (slip) => (
        <div className="cell-stack">
          <span style={TRUNCATE} title={slip.customerName}>
            {slip.customerName}
          </span>
          <small style={TRUNCATE} title={formatAddress(slip.deliveryAddress)}>
            {slip.deliverySiteName}
            {slip.deliveryAddress?.city ? ` · ${slip.deliveryAddress.city}` : ""}
          </small>
        </div>
      )
    },
    {
      key: "items",
      header: "Items",
      render: (slip) => (
        <div className="cell-stack">
          <span style={TRUNCATE} title={slip.itemsSummary}>
            {slip.itemsSummary}
          </span>
          <small className="nowrap">{formatNumber(slip.cylindersAllocated)} cylinders</small>
        </div>
      )
    },
    {
      key: "crew",
      header: "Van & crew",
      sortValue: (slip) => slip.vehicleNumber,
      render: (slip) => (
        <div className="cell-stack">
          <span className="mono nowrap">{slip.vehicleNumber}</span>
          <small style={TRUNCATE}>
            {slip.driverName}
            {slip.helperName ? ` + ${slip.helperName}` : ""}
          </small>
        </div>
      )
    },
    {
      key: "date",
      header: "Scheduled",
      sortValue: (slip) => slip.scheduledDate,
      render: (slip) => (
        <div className="cell-stack">
          <span className="nowrap">{formatDate(slip.scheduledDate)}</span>
          <small className="nowrap">
            {slip.deliveredAt
              ? `Delivered ${formatRelativeTime(slip.deliveredAt)}`
              : slip.dispatchedAt
                ? `Left ${formatRelativeTime(slip.dispatchedAt)}`
                : formatCurrency(slip.totalAmount)}
          </small>
        </div>
      )
    },
    { key: "status", header: "Status", sortValue: (slip) => slip.status, render: (slip) => <DeliveryStatusBadge status={slip.status} /> }
  ];

  return (
    <div className="page admin-deliveries-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "The agency dispatch board: delivery slips, vehicles, assigned crew and live fulfillment status." : "The dispatch board: every delivery slip, its van and crew, and where it stands."}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            <ButtonLink variant="secondary" to={`${isMerchantPanel?"/merchant":"/admin"}/deliveries/trips?merchant=${encodeURIComponent(merchantId || "")}`}>Trips & routes</ButtonLink>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => {
                    setOpenId(null);
                    setFilter("merchant", event.target.value);
                  }}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            <Button variant="secondary" icon="refresh" onClick={invalidate} disabled={!merchantId || query.isFetching}>
              Refresh
            </Button>
          </>
        }
      />

      {merchants.error ? <InlineError error={merchants.error} title="Merchants could not be loaded" onRetry={() => void merchants.refetch()} /> : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState icon="store" title="Choose a merchant" description="Deliveries are kept per merchant. Pick one above." />
          </Card>
        )
      ) : (
        <>
          <div className="kpi-grid" aria-label="Delivery summary">
            <StatCard label="Scheduled" icon="calendar" tone="blue" value={ready ? formatNumber(counts.SCHEDULED) : "—"} hint="Waiting to leave the godown" />
            <StatCard
              label="On the road"
              icon="truck"
              tone="orange"
              value={ready ? formatNumber(counts.DISPATCHED + counts.ON_LOCATION) : "—"}
              hint={ready ? `${formatNumber(counts.ON_LOCATION)} at the customer now` : "Dispatched or at the customer"}
            />
            <StatCard label="Delivered" icon="checkCircle" tone="green" value={ready ? formatNumber(counts.DELIVERED) : "—"} hint="Confirmed by the customer" />
            <StatCard
              label="Failed"
              icon="xCircle"
              tone={counts.FAILED ? "red" : "slate"}
              value={ready ? formatNumber(counts.FAILED) : "—"}
              hint={ready ? `${formatNumber(counts.pendingPickup)} empties still to collect` : "Did not deliver"}
            />
          </div>

          <Card bodyless className="table-card">
            <div className="status-tabs status-tabs--card" role="tablist" aria-label="Delivery status">
              {TABS.map((item) => (
                <button key={item.value} type="button" role="tab" aria-selected={tab === item.value} onClick={() => setFilter("status", item.value === "ALL" ? "" : item.value)}>
                  {item.label}
                  {item.value !== "ALL" && counts[item.value] ? <span className="tab-count">{counts[item.value]}</span> : null}
                </button>
              ))}
            </div>

            <TableHeader
              title={TABS.find((item) => item.value === tab)?.label ?? "Deliveries"}
              count={query.data?.length}
              description="On the road first, then what still has to go out, then failures, then delivered."
            />

            <FilterBar onReset={() => setFilter("search", "")} canReset={Boolean(values.search)}>
              <SearchInput
                label="Search deliveries"
                placeholder="Slip, order, customer, mobile, vehicle or driver"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
              />
            </FilterBar>

            {query.error && query.data ? (
              <div style={{ padding: "var(--space-4)" }}>
                <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
              </div>
            ) : null}

            <DataTable
              caption="Delivery slips"
              columns={columns}
              rows={query.data ? pageRows : undefined}
              getRowKey={(slip) => slip.id}
              onRowClick={(slip) => setOpenId(slip.id)}
              rowLabel={(slip) => slip.slipNumber}
              rowActions={(slip) => [
                { label: "View details", icon: "eye", onSelect: () => setOpenId(slip.id) },
                { label: "Change van, crew or day", icon: "truck", hidden: slip.status !== "SCHEDULED", onSelect: () => setReassigning(slip) }
              ]}
              isLoading={query.isLoading}
              error={query.data ? undefined : query.error}
              onRetry={() => void query.refetch()}
              empty={
                values.search ? (
                  <EmptyState icon="search" title="No deliveries match" description="Try a slip number, customer, vehicle or driver." />
                ) : (
                  <EmptyState icon="truck" title="No deliveries here" description="Slips are raised when an order is confirmed with a van and crew." />
                )
              }
              footer={<Pagination page={page} pageSize={PAGE_SIZE} total={rows.length} onPageChange={setPage} itemLabel="deliveries" disabled={query.isFetching} />}
            />
          </Card>
        </>
      )}

      {openId && merchantId ? (
        <DeliveryDrawer isMerchantPanel={isMerchantPanel} merchantId={merchantId} deliveryId={openId} onClose={() => setOpenId(null)} onReassign={(slip) => setReassigning(slip)} />
      ) : null}

      <ReassignDialog
        merchantId={merchantId}
        slip={reassigning}
        onClose={() => setReassigning(null)}
        onSubmit={async (input) => {
          if (!reassigning) return;
          await reassignDelivery(merchantId, reassigning.id, input);
          toast.success(`${reassigning.slipNumber} was updated.`);
          invalidate();
        }}
      />
    </div>
  );
}

function DeliveryDrawer({
  merchantId,
  deliveryId,
  onClose,
  onReassign,
  isMerchantPanel = false
}: {
  merchantId: string;
  deliveryId: string;
  onClose: () => void;
  onReassign: (slip: DeliverySlip) => void;
  isMerchantPanel?: boolean;
}) {
  const query = useQuery({
    queryKey: queryKeys.deliveries.detail(merchantId, deliveryId),
    queryFn: ({ signal }) => getDelivery(merchantId, deliveryId, signal)
  });
  const slip = query.data;

  const orderLink = slip
    ? isMerchantPanel
      ? `/merchant/orders?status=ALL&search=${encodeURIComponent(slip.orderNumber)}`
      : `/admin/orders?merchant=${encodeURIComponent(merchantId)}&status=ALL&search=${encodeURIComponent(slip.orderNumber)}`
    : "#";

  return (
    <Drawer
      open
      size="lg"
      title={slip?.slipNumber ?? "Delivery"}
      subtitle={slip ? `${slip.customerName} · order ${slip.orderNumber}` : undefined}
      meta={slip ? <DeliveryStatusBadge status={slip.status} /> : undefined}
      onClose={onClose}
      footer={
        slip ? (
          <>
            <Link className="btn btn--secondary" to={orderLink}>
              Open order
            </Link>
            {slip.status === "SCHEDULED" ? (
              <Button icon="truck" onClick={() => onReassign(slip)}>
                Change van, crew or day
              </Button>
            ) : null}
          </>
        ) : undefined
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading delivery" />
      ) : query.error || !slip ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {slip.status === "FAILED" && slip.failureReason ? (
            <Alert tone="error" title="Delivery failed">
              {slip.failureReason}
            </Alert>
          ) : null}

          <DrawerSection title="Van & crew">
            <DetailsPanel
              items={[
                { label: "Vehicle", value: <span className="mono">{slip.vehicleNumber}</span> },
                { label: "Scheduled for", value: formatDate(slip.scheduledDate) },
                { label: "Driver", value: slip.driverName },
                { label: "Helper", value: slip.helperName || "—" },
                { label: "Left godown", value: slip.dispatchedAt ? formatDateTime(slip.dispatchedAt) : "Not yet" },
                { label: "Delivered", value: slip.deliveredAt ? formatDateTime(slip.deliveredAt) : "Not yet" }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="Drop-off">
            <DetailsPanel
              items={[
                { label: "Customer", value: slip.customerName },
                { label: "Site", value: slip.deliverySiteName },
                { label: "Address", value: formatAddress(slip.deliveryAddress) },
                { label: "Confirmation", value: slip.confirmationMethod === "NONE" ? "None" : slip.confirmationMethod },
                { label: "Dev code", value: <span className="mono">{slip.devConfirmationCode}</span>, hidden: !slip.devConfirmationCode }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="Cylinders">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Cylinder</th>
                    <th style={{ textAlign: "right" }}>Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {slip.items.map((item) => (
                    <tr key={item.cylinderType}>
                      <td>{item.cylinderLabel}</td>
                      <td style={{ textAlign: "right" }}>{formatNumber(item.quantity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <DetailsPanel
              items={[
                { label: "Allocated", value: formatNumber(slip.cylindersAllocated) },
                { label: "Empties collected", value: formatNumber(slip.emptiesCollected) },
                { label: "Empties still due", value: formatNumber(slip.pendingPickup) }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="Amount">
            <DetailsPanel
              items={[
                { label: "Subtotal", value: formatCurrency(slip.subtotal) },
                { label: `GST (${slip.gstPercent}%)`, value: formatCurrency(slip.gstAmount) },
                { label: "Total", value: <strong>{formatCurrency(slip.totalAmount)}</strong> }
              ]}
            />
          </DrawerSection>

          {slip.note ? (
            <DrawerSection title="Note">
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{slip.note}</p>
            </DrawerSection>
          ) : null}
        </>
      )}
    </Drawer>
  );
}

function ReassignDialog({
  merchantId,
  slip,
  onClose,
  onSubmit
}: {
  merchantId: string;
  slip: DeliverySlip | null;
  onClose: () => void;
  onSubmit: (input: ReassignDeliveryInput) => Promise<void>;
}) {
  const eligible = useQuery({
    queryKey: queryKeys.vehicles.forDelivery(merchantId, slip?.id ?? ""),
    queryFn: ({ signal }) => listDeliveryEligibleVehicles(merchantId, slip!.id, signal),
    enabled: Boolean(slip && merchantId),
    staleTime: 30_000,
    retry: false
  });
  const [form, setForm] = useState({ vehicleNumber: "", driverName: "", helperName: "", deliveryDate: "", reason: "" });
  useEffect(() => {
    if (slip) {
      setForm({
        vehicleNumber: slip.vehicleNumber,
        driverName: slip.driverName,
        helperName: slip.helperName ?? "",
        deliveryDate: slip.scheduledDate,
        reason: ""
      });
    }
  }, [slip]);

  const mutation = useMutation({ mutationFn: onSubmit, onSuccess: onClose });

  // Only what changed is sent, so the backend leaves everything else alone.
  const input: ReassignDeliveryInput = slip
    ? {
        ...(form.vehicleNumber.trim().toUpperCase() !== slip.vehicleNumber ? { vehicleNumber: form.vehicleNumber.trim().toUpperCase() } : {}),
        ...(form.driverName.trim() !== slip.driverName ? { driverName: form.driverName.trim() } : {}),
        ...(form.helperName.trim() !== (slip.helperName ?? "") ? { helperName: form.helperName.trim() } : {}),
        ...(form.deliveryDate !== slip.scheduledDate ? { deliveryDate: form.deliveryDate } : {})
      }
    : {};
  const changed = Object.keys(input).length > 0;
  const invalid = !form.vehicleNumber.trim() || !form.driverName.trim() || !form.deliveryDate;

  function submit() {
    if (!changed || invalid) return;
    mutation.mutate({ ...input, reason: form.reason.trim() || undefined });
  }

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((previous) => ({ ...previous, [key]: event.target.value }));

  return (
    <Modal
      open={slip !== null}
      title="Change van, crew or day"
      description={slip ? `${slip.slipNumber} for ${slip.customerName}. Only what you change is updated; the order keeps its number and history.` : undefined}
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={submit} disabled={!changed || invalid} loading={mutation.isPending} loadingText="Saving…">
            Save changes
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="grid-2">
          <EligibleVehicleField
            vehicles={eligible.data}
            loading={eligible.isLoading}
            failed={Boolean(eligible.error)}
            value={form.vehicleNumber}
            onChange={(vehicleNumber) => setForm((previous) => ({ ...previous, vehicleNumber }))}
            error={!form.vehicleNumber.trim() ? "Choose or enter the vehicle." : undefined}
          />
          <Field label="Delivery date" required>
            <Input type="date" min={todayInputValue()} value={form.deliveryDate} onChange={set("deliveryDate")} />
          </Field>
          <Field label="Driver" required error={!form.driverName.trim() ? "Enter the driver's name." : undefined}>
            <Input value={form.driverName} onChange={set("driverName")} maxLength={160} />
          </Field>
          <Field label="Helper" optional>
            <Input value={form.helperName} onChange={set("helperName")} maxLength={160} />
          </Field>
        </div>
        <Field label="Reason" optional hint="Recorded on the slip, e.g. van off the road.">
          <Textarea value={form.reason} onChange={set("reason")} rows={2} maxLength={500} />
        </Field>
        {!changed ? <p className="meta">Change at least one field to save.</p> : null}
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

export default AdminDeliveriesPage;
