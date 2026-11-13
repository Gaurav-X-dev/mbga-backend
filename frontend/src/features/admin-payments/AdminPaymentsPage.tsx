import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { normalizeError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import {
  getPayment,
  listInvoices,
  listPayments,
  reconcilePayment,
  recordPayment,
  type Invoice,
  type InvoiceStatus,
  type Payment,
  type PaymentMode,
  type ReconciliationStatus
} from "../../api/payments.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { InvoiceDrawer } from "./InvoiceDrawer";
import { PaymentProof } from "./PaymentProof";
import { useInvoicePdf } from "./useInvoicePdf";
import { Checkbox, Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatDate, formatDateTime, formatNumber, formatRelativeTime, todayInputValue } from "../../utils/format";
import type { Tone } from "../../utils/labels";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "view", "status", "search", "open", "invoice", "istatus", "customer"] as const;

const INVOICE_TABS = [
  { value: "", label: "All" },
  { value: "UNPAID", label: "Unpaid" },
  { value: "PARTIAL", label: "Partial" },
  { value: "PAID", label: "Paid" },
  { value: "OVERDUE", label: "Overdue" }
] as const;

const invoiceMatchesTab = (i: Invoice, tab: string) =>
  !tab ? true : tab === "OVERDUE" ? i.isOverdue && i.balance > 0 : i.status === tab;

const RECON_META: Record<ReconciliationStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "Pending check", tone: "warning" },
  RECONCILED: { label: "Reconciled", tone: "success" },
  INVALID: { label: "Invalid", tone: "danger" }
};

const INVOICE_META: Record<InvoiceStatus, { label: string; tone: Tone }> = {
  UNPAID: { label: "Unpaid", tone: "danger" },
  PARTIAL: { label: "Part paid", tone: "warning" },
  PAID: { label: "Paid", tone: "success" }
};

const MODE_LABEL: Record<PaymentMode, string> = { ADVANCE: "Advance adjustment", CASH: "Cash", UPI: "UPI", NEFT: "NEFT", SPLIT: "Cash + UPI" };

const RECON_TABS = [
  { value: "ALL", label: "All" },
  { value: "PENDING", label: "Pending check" },
  { value: "RECONCILED", label: "Reconciled" },
  { value: "INVALID", label: "Invalid" }
];

const TRUNCATE = { display: "block", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;

export function AdminPaymentsPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = isMerchantPanel ? "Agency Payments & Invoices" : "Payments"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setFilters, setPage } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const view = values.view === "invoices" ? "invoices" : "payments";
  const reconTab = values.status || "ALL";
  const openOnly = values.open === "1";

  const [openPaymentId, setOpenPaymentId] = useState<string | null>(null);
  const [recordFor, setRecordFor] = useState<Invoice | "pick" | null>(null);

  // Money is kept per merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  const enabled = Boolean(merchantId);
  const paymentParams = { merchantId, reconciliationStatus: reconTab, search: values.search || undefined };
  const payments = useQuery({
    queryKey: queryKeys.payments.list(paymentParams),
    queryFn: ({ signal }) => listPayments(paymentParams, signal),
    enabled: enabled && view === "payments",
    placeholderData: keepPreviousData
  });
  // Unfiltered lists feed the summary cards so they do not move with the tabs.
  const allPaymentParams = { merchantId, reconciliationStatus: "ALL" };
  const allPayments = useQuery({
    queryKey: queryKeys.payments.list(allPaymentParams),
    queryFn: ({ signal }) => listPayments(allPaymentParams, signal),
    enabled,
    staleTime: 30_000
  });
  const pdf = useInvoicePdf(merchantId);
  // The full list feeds the summary cards and the customer picker; the customer filter is a server query.
  const invoiceParams = { merchantId };
  const invoices = useQuery({
    queryKey: queryKeys.payments.invoices(invoiceParams),
    queryFn: ({ signal }) => listInvoices(invoiceParams, signal),
    enabled
  });

  const stats = useMemo(() => {
    const paymentRows = allPayments.data ?? [];
    const invoiceRows = invoices.data ?? [];
    const pending = paymentRows.filter((p) => p.reconciliationStatus === "PENDING");
    return {
      collected: paymentRows.reduce((s, p) => s + (p.effectiveAmount ?? (p.reconciliationStatus === "INVALID" ? 0 : p.amountCollected)), 0),
      pendingCount: pending.length,
      pendingAmount: pending.reduce((s, p) => s + (p.mode === "SPLIT" ? p.upiAmount ?? 0 : p.amountCollected), 0),
      outstanding: invoiceRows.reduce((s, i) => s + i.balance, 0),
      openInvoices: invoiceRows.filter((i) => i.balance > 0).length,
      overdueCount: invoiceRows.filter((i) => i.isOverdue && i.balance > 0).length,
      overdueAmount: invoiceRows.filter((i) => i.isOverdue && i.balance > 0).reduce((s, i) => s + i.balance, 0),
      invalidCount: paymentRows.filter((p) => p.reconciliationStatus === "INVALID").length
    };
  }, [allPayments.data, invoices.data]);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.payments.all });
  }

  const paymentColumns: Column<Payment>[] = [
    {
      key: "payment",
      header: "Payment",
      primary: true,
      sortValue: (p) => p.paidAt,
      render: (p) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setOpenPaymentId(p.id)}>
            {p.paymentNumber}
          </button>
          <small className="nowrap" title={formatDateTime(p.paidAt)}>
            {formatDate(p.paidAt)} · {formatRelativeTime(p.paidAt)}
          </small>
        </div>
      )
    },
    {
      key: "customer",
      header: "Customer",
      sortValue: (p) => p.customerName,
      render: (p) => (
        <div className="cell-stack">
          <span style={TRUNCATE} title={p.customerName}>
            {p.customerName}
          </span>
          <small className="nowrap">{p.invoiceNumber}</small>
        </div>
      )
    },
    {
      key: "mode",
      header: "Mode",
      sortValue: (p) => p.mode,
      render: (p) => (
        <div className="cell-stack">
          <span className="nowrap">
            {MODE_LABEL[p.mode] ?? p.mode}
            {p.proofUrl ? (
              <>
                {" "}
                <Badge tone="info">Proof</Badge>
              </>
            ) : null}
          </span>
          <small style={TRUNCATE} className="mono" title={p.reference ?? undefined}>
            {p.reference || (p.mode === "CASH" ? "—" : "No reference")}
          </small>
        </div>
      )
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      sortValue: (p) => p.amountCollected,
      render: (p) => (
        <div className="cell-stack" style={{ alignItems: "flex-end" }}>
          <strong className="nowrap">{formatCurrency(p.amountCollected)}</strong>
          <small className="nowrap">of {formatCurrency(p.invoiceAmount)}</small>
        </div>
      )
    },
    {
      key: "status",
      header: "Status",
      sortValue: (p) => p.reconciliationStatus,
      render: (p) => <Badge tone={RECON_META[p.reconciliationStatus]?.tone ?? "neutral"}>{RECON_META[p.reconciliationStatus]?.label ?? p.reconciliationStatus}</Badge>
    }
  ];

  const customerInvoiceParams = { merchantId, customerId: values.customer };
  const customerInvoices = useQuery({
    queryKey: queryKeys.payments.invoices(customerInvoiceParams),
    queryFn: ({ signal }) => listInvoices(customerInvoiceParams, signal),
    enabled: enabled && view === "invoices" && Boolean(values.customer)
  });
  const invoiceSource = values.customer ? customerInvoices : invoices;
  const invoiceCustomers = useMemo(() => {
    const byId = new Map<string, string>();
    for (const i of invoices.data ?? []) byId.set(i.customerId, i.customerName);
    return [...byId].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [invoices.data]);
  const tabCount = (tab: string) => (invoiceSource.data ?? []).filter((i) => invoiceMatchesTab(i, tab)).length;

  const invoiceRows = (invoiceSource.data ?? []).filter((i) => {
    if (!invoiceMatchesTab(i, values.istatus)) return false;
    if (openOnly && i.balance <= 0) return false;
    if (!values.search) return true;
    const q = values.search.toLowerCase();
    return [i.invoiceNumber, i.orderNumber, i.customerName].some((v) => v.toLowerCase().includes(q));
  });

  const invoiceColumns: Column<Invoice>[] = [
    {
      key: "invoice",
      header: "Invoice",
      primary: true,
      sortValue: (i) => i.issuedAt,
      render: (i) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setFilter("invoice", i.id)}>
            {i.invoiceNumber}
          </button>
          <small className="nowrap">
            <Link to={`/admin/orders?merchant=${encodeURIComponent(merchantId)}&status=ALL&search=${encodeURIComponent(i.orderNumber)}`}>{i.orderNumber}</Link>
            {i.isGstInvoice ? " · GST" : ""}
          </small>
        </div>
      )
    },
    {
      key: "customer",
      header: "Customer",
      sortValue: (i) => i.customerName,
      render: (i) => (
        <span style={TRUNCATE} title={i.customerName}>
          {i.customerName}
        </span>
      )
    },
    {
      key: "dates",
      header: "Due",
      sortValue: (i) => i.dueAt,
      render: (i) => (
        <div className="cell-stack">
          <span className="nowrap" style={i.isOverdue && i.balance > 0 ? { color: "var(--red-600, #dc2626)", fontWeight: 600 } : undefined}>
            {formatDate(i.dueAt)}
            {i.isOverdue && i.balance > 0 ? " · Overdue" : ""}
          </span>
          <small className="nowrap">Issued {formatDate(i.issuedAt)}</small>
        </div>
      )
    },
    { key: "total", header: "Total", align: "right", sortValue: (i) => i.totalAmount, render: (i) => <span className="nowrap">{formatCurrency(i.totalAmount)}</span> },
    { key: "paid", header: "Paid", align: "right", sortValue: (i) => i.paidAmount, render: (i) => <span className="nowrap">{formatCurrency(i.paidAmount)}</span> },
    { key: "balance", header: "Balance", align: "right", sortValue: (i) => i.balance, render: (i) => <strong className="nowrap">{formatCurrency(i.balance)}</strong> },
    {
      key: "status",
      header: "Status",
      sortValue: (i) => i.status,
      render: (i) => <Badge tone={INVOICE_META[i.status]?.tone ?? "neutral"}>{INVOICE_META[i.status]?.label ?? i.status}</Badge>
    }
  ];

  const paymentRows = payments.data ?? [];
  const pageOf = <T,>(rows: T[]) => rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const ready = Boolean(allPayments.data && invoices.data);

  return (
    <div className="page admin-payments-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Money collected against invoices, collections log and customer tax invoices." : "Money collected against invoices, and the checks that confirm it reached the bank."}
        meta={<RefreshIndicator active={(payments.isFetching || invoices.isFetching) && !payments.isLoading} />}
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => {
                    setOpenPaymentId(null);
                    setFilter("merchant", event.target.value);
                  }}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            <Button icon="plus" onClick={() => setRecordFor("pick")} disabled={!enabled}>
              Record payment
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
            <EmptyState icon="store" title="Choose a merchant" description="Payments are kept per merchant. Pick one above." />
          </Card>
        )
      ) : (
        <>
          <div className="kpi-grid" aria-label="Payment summary">
            <StatCard label="Collected" icon="wallet" tone="green" value={ready ? formatCurrency(stats.collected) : "—"} hint="All payments, excluding invalid" />
            <StatCard
              label="Awaiting bank check"
              icon="clock"
              tone="amber"
              value={ready ? formatNumber(stats.pendingCount) : "—"}
              hint={ready ? `${formatCurrency(stats.pendingAmount)} in UPI / NEFT` : "UPI and NEFT to match"}
            />
            <StatCard
              label="Outstanding"
              icon="fileText"
              tone="blue"
              value={ready ? formatCurrency(stats.outstanding) : "—"}
              hint={ready ? `${formatNumber(stats.openInvoices)} open invoices` : "Still owed on invoices"}
            />
            <StatCard
              label="Overdue"
              icon="warning"
              tone={stats.overdueCount ? "red" : "slate"}
              value={ready ? formatCurrency(stats.overdueAmount) : "—"}
              hint={ready ? `${formatNumber(stats.overdueCount)} invoices past due` : "Past the due date"}
            />
          </div>

          <Card bodyless className="table-card">
            <div className="status-tabs status-tabs--card" role="tablist" aria-label="Payments or invoices">
              <button type="button" role="tab" aria-selected={view === "payments"} onClick={() => setFilter("view", "")}>
                Payments
                {stats.pendingCount ? <span className="tab-count">{stats.pendingCount}</span> : null}
              </button>
              <button type="button" role="tab" aria-selected={view === "invoices"} onClick={() => setFilter("view", "invoices")}>
                Invoices
                {stats.openInvoices ? <span className="tab-count">{stats.openInvoices}</span> : null}
              </button>
            </div>

            {view === "payments" ? (
              <>
                <TableHeader
                  title="Payments"
                  count={payments.data?.length}
                  description="Newest collected first. Cash is reconciled on entry; UPI and NEFT wait for a bank check."
                />
                <FilterBar onReset={() => setFilter("search", "")} canReset={Boolean(values.search)}>
                  <SearchInput label="Search payments" placeholder="Payment, invoice, customer or reference" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
                  <Field label="Reconciliation" hideLabel>
                    <Select
                      value={reconTab === "ALL" ? "" : reconTab}
                      onChange={(e) => setFilter("status", e.target.value)}
                      placeholder="Any status"
                      options={RECON_TABS.filter((t) => t.value !== "ALL")}
                    />
                  </Field>
                </FilterBar>
                {stats.invalidCount && reconTab !== "INVALID" ? (
                  <div style={{ padding: "0 var(--space-4) var(--space-3)" }}>
                    <Alert tone="warning">
                      {stats.invalidCount} payment{stats.invalidCount === 1 ? " was" : "s were"} marked invalid.{" "}
                      <button type="button" className="btn--link" onClick={() => setFilter("status", "INVALID")}>
                        Review
                      </button>
                    </Alert>
                  </div>
                ) : null}
                <DataTable
                  caption="Payments"
                  columns={paymentColumns}
                  rows={payments.data ? pageOf(paymentRows) : undefined}
                  getRowKey={(p) => p.id}
                  onRowClick={(p) => setOpenPaymentId(p.id)}
                  rowLabel={(p) => p.paymentNumber}
                  rowActions={(p) => [{ label: "View details", icon: "eye", onSelect: () => setOpenPaymentId(p.id) }]}
                  isLoading={payments.isLoading}
                  error={payments.data ? undefined : payments.error}
                  onRetry={() => void payments.refetch()}
                  empty={
                    values.search || reconTab !== "ALL" ? (
                      <EmptyState icon="search" title="No payments match" description="Try a different search or status." />
                    ) : (
                      <EmptyState icon="wallet" title="No payments yet" description="Payments recorded here or collected by drivers appear in this list." />
                    )
                  }
                  footer={<Pagination page={page} pageSize={PAGE_SIZE} total={paymentRows.length} onPageChange={setPage} itemLabel="payments" disabled={payments.isFetching} />}
                />
              </>
            ) : (
              <>
                <div className="status-tabs" role="tablist" aria-label="Invoice status" style={{ padding: "0 var(--space-4)" }}>
                  {INVOICE_TABS.map((tab) => (
                    <button key={tab.label} type="button" role="tab" aria-selected={values.istatus === tab.value} onClick={() => setFilter("istatus", tab.value)}>
                      {tab.label}
                      {invoiceSource.data ? <span className="tab-count">{tabCount(tab.value)}</span> : null}
                    </button>
                  ))}
                </div>
                <TableHeader title="Invoices" count={invoiceRows.length} description="Newest issued first. Raised automatically when an order is delivered." />
                <FilterBar onReset={() => setFilters({ search: "", customer: "", open: "", istatus: "" })} canReset={Boolean(values.search || values.customer || values.open || values.istatus)}>
                  <SearchInput label="Search invoices" placeholder="Invoice, order or customer" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
                  <Field label="Customer" hideLabel>
                    <Select value={values.customer} onChange={(e) => setFilter("customer", e.target.value)} placeholder="All customers" options={invoiceCustomers} />
                  </Field>
                  <Checkbox label="Only with a balance owing" checked={openOnly} onChange={(e) => setFilter("open", e.target.checked ? "1" : "")} />
                </FilterBar>
                <DataTable
                  caption="Invoices"
                  columns={invoiceColumns}
                  rows={invoiceSource.data ? pageOf(invoiceRows) : undefined}
                  getRowKey={(i) => i.id}
                  onRowClick={(i) => setFilter("invoice", i.id)}
                  rowLabel={(i) => i.invoiceNumber}
                  rowActions={(i) => [
                    { label: "View invoice", icon: "eye", onSelect: () => setFilter("invoice", i.id) },
                    { label: "Download PDF", icon: "download", disabled: pdf.isBusy(i.id), onSelect: () => void pdf.download(i) },
                    { label: "Share PDF", icon: "send", disabled: pdf.isBusy(i.id), onSelect: () => void pdf.share(i) },
                    { label: "Record payment", icon: "wallet", hidden: i.balance <= 0, onSelect: () => setRecordFor(i) },
                    {
                      label: "View payments",
                      icon: "eye",
                      onSelect: () => setFilters({ view: "", status: "", search: i.invoiceNumber })
                    }
                  ]}
                  isLoading={invoiceSource.isLoading}
                  error={invoiceSource.data ? undefined : invoiceSource.error}
                  onRetry={() => void invoiceSource.refetch()}
                  empty={
                    values.search || values.customer || values.istatus || openOnly ? (
                      <EmptyState icon="search" title="No invoices match" description={values.istatus === "OVERDUE" ? "Nothing is past due." : "Try another status, customer or search."} />
                    ) : (
                      <EmptyState icon="fileText" title="No invoices yet" description="Invoices are raised automatically when an order is delivered." />
                    )
                  }
                  footer={<Pagination page={page} pageSize={PAGE_SIZE} total={invoiceRows.length} onPageChange={setPage} itemLabel="invoices" disabled={invoiceSource.isFetching} />}
                />
              </>
            )}
          </Card>
        </>
      )}

      {openPaymentId && merchantId ? (
        <PaymentDrawer
          merchantId={merchantId}
          paymentId={openPaymentId}
          onClose={() => setOpenPaymentId(null)}
          onChanged={(message) => {
            toast.success(message);
            invalidate();
          }}
        />
      ) : null}

      {values.invoice && merchantId ? (
        <InvoiceDrawer
          merchantId={merchantId}
          invoiceId={values.invoice}
          onClose={() => setFilter("invoice", "")}
          onRecordPayment={(invoice) => setRecordFor(invoice)}
          onOpenPayment={(paymentId) => {
            setFilter("invoice", "");
            setOpenPaymentId(paymentId);
          }}
        />
      ) : null}

      <RecordPaymentDialog
        merchantId={merchantId}
        target={recordFor}
        invoices={(invoices.data ?? []).filter((i) => i.balance > 0)}
        onClose={() => setRecordFor(null)}
        onRecorded={(payment) => {
          toast.success(`${payment.paymentNumber} recorded: ${formatCurrency(payment.amountCollected)} from ${payment.customerName}.`);
          invalidate();
        }}
      />
    </div>
  );
}

function PaymentDrawer({
  merchantId,
  paymentId,
  onClose,
  onChanged
}: {
  merchantId: string;
  paymentId: string;
  onClose: () => void;
  onChanged: (message: string) => void;
}) {
  const query = useQuery({
    queryKey: queryKeys.payments.detail(merchantId, paymentId),
    queryFn: ({ signal }) => getPayment(merchantId, paymentId, signal)
  });
  const payment = query.data;
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: ({ reconciled, why }: { reconciled: boolean; why?: string }) => reconcilePayment(merchantId, paymentId, reconciled, why),
    onSuccess: (result) => {
      setRejecting(false);
      setReason("");
      void query.refetch();
      onChanged(result.reconciliationStatus === "RECONCILED" ? `${result.paymentNumber} reconciled.` : `${result.paymentNumber} marked invalid; the outstanding balance is unchanged.`);
    }
  });

  const pending = payment?.reconciliationStatus === "PENDING";

  return (
    <Drawer
      open
      size="lg"
      title={payment?.paymentNumber ?? "Payment"}
      subtitle={payment ? `${payment.customerName} · ${formatCurrency(payment.amountCollected)} by ${MODE_LABEL[payment.mode] ?? payment.mode}` : undefined}
      meta={payment ? <Badge tone={RECON_META[payment.reconciliationStatus]?.tone ?? "neutral"}>{RECON_META[payment.reconciliationStatus]?.label}</Badge> : undefined}
      onClose={onClose}
      footer={
        pending && !rejecting ? (
          <>
            <Button variant="danger" icon="xCircle" onClick={() => setRejecting(true)} disabled={mutation.isPending}>
              Money not received
            </Button>
            <Button icon="checkCircle" onClick={() => mutation.mutate({ reconciled: true })} loading={mutation.isPending} loadingText="Saving…">
              Matches bank statement
            </Button>
          </>
        ) : undefined
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading payment" />
      ) : query.error || !payment ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {payment.reconciliationStatus === "INVALID" ? (
            <Alert tone="error" title="Marked invalid">
              {payment.invalidReason || "The money did not reach the bank."} {payment.mode === "SPLIT" ? "The UPI portion was not applied; cash remains paid." : "The pending amount was not applied to the invoice."}
            </Alert>
          ) : pending ? (
            <Alert tone="warning" title="Check against the bank statement">
              Match reference <strong className="mono">{payment.reference || "—"}</strong> for {formatCurrency(payment.mode === "SPLIT" ? payment.upiAmount ?? 0 : payment.amountCollected)} before reconciling.
              {payment.proofUrl ? " A screenshot is evidence, not confirmation — check the statement." : ""}
            </Alert>
          ) : null}

          {rejecting ? (
            <DrawerSection title="Why is this payment invalid?">
              <form
                className="stack"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (reason.trim()) mutation.mutate({ reconciled: false, why: reason.trim() });
                }}
              >
                <Field label="Reason" required hint="The amount remains outstanding. Explain why the payment could not be verified.">
                  <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} autoFocus placeholder="e.g. No credit with this UTR on the statement" />
                </Field>
                <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
                  <Button variant="secondary" onClick={() => setRejecting(false)} disabled={mutation.isPending}>
                    Back
                  </Button>
                  <Button type="submit" variant="danger" disabled={!reason.trim()} loading={mutation.isPending} loadingText="Saving…">
                    Mark invalid
                  </Button>
                </div>
              </form>
            </DrawerSection>
          ) : null}

          {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}

          <DrawerSection title="Payment">
            <DetailsPanel
              items={[
                { label: "Amount collected", value: <strong>{formatCurrency(payment.amountCollected)}</strong> },
                { label: "Mode", value: MODE_LABEL[payment.mode] ?? payment.mode },
                ...(payment.mode === "SPLIT" ? [
                  { label: "Cash", value: formatCurrency(payment.cashAmount ?? 0) },
                  { label: "UPI", value: formatCurrency(payment.upiAmount ?? 0) }
                ] : []),
                { label: "Reference", value: payment.reference ? <span className="mono">{payment.reference}</span> : "—" },
                { label: "Paid at", value: formatDateTime(payment.paidAt) },
                { label: "Collected by", value: payment.collectedBy || "—" },
                { label: "Note", value: payment.note || "—" }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="Payment proof">
            <PaymentProof merchantId={merchantId} payment={payment} />
          </DrawerSection>

          <DrawerSection title="Invoice & customer">
            <DetailsPanel
              items={[
                { label: "Invoice", value: payment.invoiceNumber },
                { label: "Invoice amount", value: formatCurrency(payment.invoiceAmount) },
                { label: "Customer", value: payment.customerName },
                { label: "Customer still owes", value: <strong>{formatCurrency(payment.customerRunningBalance)}</strong> }
              ]}
            />
          </DrawerSection>
        </>
      )}
    </Drawer>
  );
}

function RecordPaymentDialog({
  merchantId,
  target,
  invoices,
  onClose,
  onRecorded
}: {
  merchantId: string;
  /** An invoice to pay, "pick" to choose one, or null when closed. */
  target: Invoice | "pick" | null;
  invoices: Invoice[];
  onClose: () => void;
  onRecorded: (payment: Payment) => void;
}) {
  const open = target !== null;
  const [form, setForm] = useState({ invoiceId: "", amount: "", mode: "CASH" as PaymentMode, cashAmount: "", upiAmount: "", reference: "", paidAt: "", note: "" });
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    const invoice = target !== "pick" ? target : null;
    setForm({
      invoiceId: invoice?.id ?? "",
      amount: invoice ? String(invoice.balance) : "",
      mode: "CASH",
      cashAmount: "",
      upiAmount: "",
      reference: "",
      paidAt: todayInputValue(),
      note: ""
    });
    setSubmitted(false);
  }, [open, target]);

  const invoice = (target !== "pick" && target) || invoices.find((i) => i.id === form.invoiceId) || null;
  const amount = Number(form.amount);

  const mutation = useMutation({
    mutationFn: () =>
      recordPayment(merchantId, {
        invoiceId: form.invoiceId,
        amount: Math.round(amount),
        mode: form.mode,
        cashAmount: form.mode === "SPLIT" ? Number(form.cashAmount) : undefined,
        upiAmount: form.mode === "SPLIT" ? Number(form.upiAmount) : undefined,
        reference: form.reference.trim() || undefined,
        // A date input has no time; noon IST keeps it on the chosen day in every time zone.
        paidAt: form.paidAt ? `${form.paidAt}T12:00:00+05:30` : undefined,
        note: form.note.trim() || undefined
      }),
    onSuccess: (payment) => {
      onRecorded(payment);
      onClose();
    }
  });

  const errors = {
    invoiceId: form.invoiceId ? undefined : "Choose the invoice being paid.",
    // Only a positive amount is checked here; the backend decides what an invoice can take.
    amount: !(amount > 0) ? "Enter an amount greater than 0." : undefined,
    reference: form.mode !== "CASH" && !form.reference.trim() ? `Enter the ${form.mode === "UPI" ? "UPI transaction ID" : "UTR number"}.` : undefined,
    split: form.mode === "SPLIT" && !(Number(form.cashAmount) > 0 && Number(form.upiAmount) > 0 &&
      Number(form.cashAmount) + Number(form.upiAmount) === amount &&
      Number.isInteger(Number(form.cashAmount)) && Number.isInteger(Number(form.upiAmount)))
      ? "Cash + UPI must equal the total amount in whole rupees." : undefined,
    paidAt: form.paidAt > todayInputValue() ? "Cannot be in the future." : undefined
  };
  const valid = !Object.values(errors).some(Boolean);
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((previous) => ({ ...previous, [key]: event.target.value }));

  return (
    <Modal
      open={open}
      title="Record payment"
      description={invoice ? `${invoice.invoiceNumber} · ${invoice.customerName}` : "Money collected against an open invoice."}
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
          <Button
            icon="check"
            onClick={() => {
              setSubmitted(true);
              if (valid) mutation.mutate();
            }}
            loading={mutation.isPending}
            loadingText="Recording…"
          >
            Record {!errors.amount ? formatCurrency(amount) : "payment"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
          if (valid) mutation.mutate();
        }}
      >
        {target === "pick" ? (
          <Field label="Invoice" required error={submitted ? errors.invoiceId : undefined}>
            <Select
              value={form.invoiceId}
              onChange={(event) => {
                const next = invoices.find((i) => i.id === event.target.value);
                setForm((previous) => ({ ...previous, invoiceId: event.target.value, amount: next ? String(next.balance) : "" }));
              }}
              placeholder={invoices.length ? "Choose an open invoice" : "No open invoices"}
              disabled={!invoices.length}
              options={invoices.map((i) => ({ value: i.id, label: `${i.invoiceNumber} · ${i.customerName} · ${formatCurrency(i.balance)} due` }))}
            />
          </Field>
        ) : null}

        {invoice ? (
          <DetailsPanel
            items={[
              { label: "Invoice total", value: formatCurrency(invoice.totalAmount) },
              { label: "Already paid", value: formatCurrency(invoice.paidAmount) },
              { label: "Still owed", value: <strong>{formatCurrency(invoice.balance)}</strong> },
              { label: "Due", value: `${formatDate(invoice.dueAt)}${invoice.isOverdue ? " · Overdue" : ""}` }
            ]}
          />
        ) : null}

        <div className="grid-2">
          <Field
            label="Amount (₹)"
            required
            error={submitted ? errors.amount : undefined}
            hint={
              invoice && !errors.amount && amount < invoice.balance ? (
                <>
                  Part payment; {formatCurrency(invoice.balance - amount)} will still be owed.{" "}
                  <button type="button" className="btn--link" onClick={() => setForm((p) => ({ ...p, amount: String(invoice.balance) }))}>
                    Pay full {formatCurrency(invoice.balance)}
                  </button>
                </>
              ) : invoice && amount > invoice.balance ? (
                <>More than the {formatCurrency(invoice.balance)} still owed.</>
              ) : undefined
            }
          >
            <Input type="number" min={1} step={1} inputMode="numeric" value={form.amount} onChange={set("amount")} />
          </Field>
          <Field label="Mode" required>
            <Select value={form.mode} onChange={set("mode")} options={(["CASH", "UPI", "SPLIT"] as PaymentMode[]).map((m) => ({ value: m, label: MODE_LABEL[m] }))} />
          </Field>
          {form.mode === "SPLIT" ? <>
            <Field label="Cash amount" required error={submitted ? errors.split : undefined}>
              <Input type="number" min={1} step={1} value={form.cashAmount} onChange={set("cashAmount")} />
            </Field>
            <Field label="UPI amount" required>
              <Input type="number" min={1} step={1} value={form.upiAmount} onChange={set("upiAmount")} />
            </Field>
          </> : null}
          <Field
            label={form.mode === "UPI" ? "UPI transaction ID" : form.mode === "NEFT" ? "UTR number" : "Reference"}
            required={form.mode !== "CASH"}
            optional={form.mode === "CASH"}
            error={submitted ? errors.reference : undefined}
          >
            <Input value={form.reference} onChange={set("reference")} maxLength={80} />
          </Field>
          <Field label="Paid on" required error={errors.paidAt}>
            <Input type="date" max={todayInputValue()} value={form.paidAt} onChange={set("paidAt")} />
          </Field>
        </div>
        <Field label="Note" optional>
          <Textarea value={form.note} onChange={set("note")} rows={2} maxLength={500} />
        </Field>
        {form.mode !== "CASH" ? (
          <p className="meta">{MODE_LABEL[form.mode]} payments stay “Pending check” until someone matches the reference against the bank statement.</p>
        ) : null}
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

export default AdminPaymentsPage;
