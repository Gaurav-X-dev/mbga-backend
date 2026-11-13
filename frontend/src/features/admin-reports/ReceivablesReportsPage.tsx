import "./receivables-reports.css";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { listMerchants } from "../../api/merchants.api";
import { normalizeError } from "../../api/errors";
import { getReceivables, getReceivableDetail, listReportGroups, exportReceivables, type ReceivableParams, type ReceivableType } from "../../api/receivables.api";
import type { ExportFormat, ReportColumn } from "../../api/reports.api";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, Pagination, type Column } from "../../components/tables/DataTable";
import { Drawer } from "../../components/feedback/Dialogs";
import { EmptyState, ErrorState } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime } from "../../utils/format";
import { expenseToday } from "../admin-expenses/expense-utils";
import { formatReportFigure } from "./report-format";
import { ReportRowDrawer, type ReportRowDetails } from "./ReportRowDrawer";
import { CustomerReportGroups } from "./CustomerReportGroups";

const FILTERS = ["type", "merchant", "customer", "group", "groupBy", "q", "customerType", "city", "overdue", "minimum", "dateFrom", "dateTo", "mode", "status", "collector", "sort", "direction"] as const;
const PAGE_SIZE = 25;
type Row = Record<string, unknown>;
function cell(value: unknown, label: string) {
  if (value == null || value === "") return "—";
  if (typeof value === "number") return formatReportFigure(label, value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  return String(value);
}
function columnsFor(columns: ReportColumn[], onOpen: (row: Row) => void, primary: string): Column<Row>[] {
  return columns.map(c => ({ key: c.key, header: c.label, align: c.align, primary: c.key === primary,
    render: row => c.key === primary
      ? <button type="button" className="btn btn--link" onClick={e => { e.stopPropagation(); onOpen(row); }}>{cell(row[c.key], c.label)}</button>
      : cell(row[c.key], c.label)
  }));
}

export function ReceivablesReportsPage({ type, merchantId: fixedMerchantId }: { type: ReceivableType; merchantId?: string }) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const { values, page, setFilter, setFilters, setPage } = useUrlFilters(FILTERS);
  const merchantId = fixedMerchantId || values.merchant || "";
  const collection = type === "CUSTOMER_COLLECTION";
  const groupBy = values.groupBy === "group" ? "group" : "customer";
  const today = expenseToday();
  const validDates = !collection || ((!values.dateFrom || values.dateFrom <= today) && (!values.dateTo || values.dateTo <= today) && (!values.dateFrom || !values.dateTo || values.dateFrom <= values.dateTo));
  const minimum = Number(values.minimum || 0);
  const validAmount = Number.isSafeInteger(minimum) && minimum >= 0;
  const params: ReceivableParams = {
    type, merchantId: merchantId || undefined, customerId: values.customer || undefined, groupId: values.group || undefined,
    groupBy, search: values.q || undefined, customerType: values.customerType || undefined, city: values.city || undefined,
    overdueOnly: !collection && values.overdue === "true", minAmount: validAmount ? minimum : 0,
    dateFrom: collection ? values.dateFrom || undefined : undefined, dateTo: collection ? values.dateTo || undefined : undefined,
    mode: collection ? values.mode || undefined : undefined, status: collection ? values.status || undefined : undefined,
    collector: collection ? values.collector || undefined : undefined,
    sortBy: values.sort === "name" ? "name" : "amount", direction: values.direction === "asc" ? "asc" : "desc",
    limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE
  };
  const enabled = validDates && validAmount;
  const report = useQuery({ queryKey: ["receivables", auth?.user?.user_id, params], queryFn: ({ signal }) => getReceivables(params, signal), enabled });
  const merchants = useQuery({ queryKey: ["receivable-merchants"], queryFn: ({ signal }) => listMerchants({ limit: 100, offset: 0 }, signal), staleTime: 300_000 });
  const groups = useQuery({ queryKey: ["report-groups", auth?.user?.user_id, merchantId], queryFn: ({ signal }) => listReportGroups(merchantId || undefined, signal) });
  const [format, setFormat] = useState<ExportFormat>("XLSX");
  const [manageGroups, setManageGroups] = useState(false);
  const [customer, setCustomer] = useState<Row | null>(null);
  const [detailPage, setDetailPage] = useState(1);
  const [details, setDetails] = useState<ReportRowDetails | null>(null);
  const detailParams = { ...params, merchantId: String(customer?.merchantId || merchantId), customerId: String(customer?.customerId || ""), offset: (detailPage - 1) * PAGE_SIZE };
  const detail = useQuery({ queryKey: ["receivables", "detail", auth?.user?.user_id, detailParams], queryFn: ({ signal }) => getReceivableDetail(detailParams, signal), enabled: Boolean(customer) && enabled });
  const exporter = useMutation({ mutationFn: () => exportReceivables(params, format), onSuccess: filename => toast.success(`Downloaded ${filename}.`), onError: error => toast.error(normalizeError(error).userMessage) });
  const open = (row: Row) => {
    if (groupBy === "group") {
      setFilters({ merchant: String(row.merchantId), group: String(row.groupId || "ungrouped"), groupBy: "customer", customer: "" });
    } else { setCustomer(row); setDetailPage(1); }
  };
  const reportColumns = columnsFor(report.data?.columns || [], open, groupBy === "group" ? "group" : "customer");
  const detailColumns: ReportColumn[] = collection
    ? [{ key: "paidAt", label: "Received at" }, { key: "reference", label: "Reference" }, { key: "mode", label: "Mode" }, { key: "collector", label: "Collector" }, { key: "appliedAmount", label: "Applied amount" }, { key: "pendingAmount", label: "Pending amount" }, { key: "invalidAmount", label: "Invalid amount" }]
    : [{ key: "invoice", label: "Invoice" }, { key: "issuedAt", label: "Issued at" }, { key: "dueAt", label: "Due at" }, { key: "amount", label: "Billed amount" }, { key: "appliedAmount", label: "Applied amount" }, { key: "balance", label: "Outstanding amount" }];
  const groupOptions = (groups.data || []).map(g => ({ value: g.id, label: `${g.name}${g.active ? "" : " (archived)"}${merchantId ? "" : ` · ${merchants.data?.items.find(m => m.id === g.merchantId)?.business_name || g.merchantId}`}` }));
  const minimumAmountField = <Field label="Minimum amount (₹)" error={validAmount ? undefined : "Enter a non-negative whole amount."}><Input type="number" min={0} step={1} value={values.minimum} onChange={e => setFilter("minimum", e.target.value)} /></Field>;
  return <div className="page admin-reports-page receivables-page">
    <PageHeader title={collection ? "Collections" : "Outstanding dues"} description="Customer-wise and group-wise receivables, with invoice and receipt details." actions={<div className="receivables-actions">
      <Button variant="secondary" onClick={() => setFilters({ type: "DAILY_DELIVERY" })}>Other reports</Button>
      {merchantId && auth?.can("customers.update") ? <Button variant="secondary" onClick={() => setManageGroups(true)}>Manage groups</Button> : null}
      <div className="receivables-export"><Field label="Export format" hideLabel><Select value={format} options={[{ value: "XLSX", label: "Excel" }, { value: "CSV", label: "CSV" }]} onChange={e => setFormat(e.target.value as ExportFormat)} /></Field>
      <Button icon="download" loading={exporter.isPending} disabled={!enabled || !report.data || report.isFetching || !auth?.can("reports.export")} onClick={() => exporter.mutate()}>Export</Button></div>
    </div>} />
    <div className="receivables-tabs" role="tablist" aria-label="Receivables report">
      <Button role="tab" aria-selected={!collection} variant={!collection ? "primary" : "secondary"} onClick={() => setFilters({ type: "OUTSTANDING_DUES", customer: "" })}>Outstanding dues</Button>
      <Button role="tab" aria-selected={collection} variant={collection ? "primary" : "secondary"} onClick={() => setFilters({ type: "CUSTOMER_COLLECTION", customer: "" })}>Collections</Button>
    </div>
    <Card className="receivables-filters">
      <div className="receivables-filter-grid">
        {!fixedMerchantId ? <Field label="Merchant"><Select value={merchantId} placeholder="All merchants" options={(merchants.data?.items || []).map(m => ({ value: m.id, label: m.business_name }))} onChange={e => { setFilters({ merchant: e.target.value, group: "", customer: "" }); setCustomer(null); }} /></Field> : null}
        <Field label="View"><Select value={groupBy} options={[{ value: "customer", label: "Customer-wise" }, { value: "group", label: "Group-wise" }]} onChange={e => setFilter("groupBy", e.target.value)} /></Field>
        <Field label="Group"><Select value={values.group} placeholder="All groups" options={[{ value: "ungrouped", label: "Ungrouped" }, ...groupOptions]} onChange={e => setFilter("group", e.target.value)} /></Field>
        <Field label="Search customers"><Input value={values.q} maxLength={160} placeholder="Name, code or mobile" onChange={e => setFilter("q", e.target.value)} /></Field>
        <Field label="Customer type"><Select value={values.customerType} placeholder="All types" options={[{ value: "RETAIL", label: "Retail" }, { value: "INDUSTRIAL", label: "Industrial" }]} onChange={e => setFilter("customerType", e.target.value)} /></Field>
        <Field label="City"><Input value={values.city} maxLength={120} onChange={e => setFilter("city", e.target.value)} /></Field>
      </div>
      {collection ? <div className="receivables-filter-grid receivables-filter-grid--secondary">
        {minimumAmountField}
        {collection ? <>
          <Field label="From"><Input type="date" max={today} value={values.dateFrom} onChange={e => setFilter("dateFrom", e.target.value)} /></Field>
          <Field label="To" error={validDates ? undefined : "Choose a valid period ending today or earlier."}><Input type="date" max={today} value={values.dateTo} onChange={e => setFilter("dateTo", e.target.value)} /></Field>
          <Field label="Payment mode"><Select value={values.mode} placeholder="All modes" options={["CASH", "UPI", "SPLIT", "NEFT"].map(value => ({ value, label: value }))} onChange={e => setFilter("mode", e.target.value)} /></Field>
          <Field label="Verification"><Select value={values.status} placeholder="All statuses" options={[{ value: "PENDING", label: "Pending" }, { value: "RECONCILED", label: "Reconciled" }, { value: "INVALID", label: "Invalid" }]} onChange={e => setFilter("status", e.target.value)} /></Field>
          <Field label="Collector"><Select value={values.collector} placeholder="All collectors" options={(report.data?.metadata?.collectors as Array<{ value: string; label: string }> | undefined) || []} onChange={e => setFilter("collector", e.target.value)} /></Field>
        </> : null}
      </div> : null}
      <div className="receivables-filter-footer">
        {!collection ? minimumAmountField : null}
        {!collection ? <label className="receivables-overdue"><input type="checkbox" checked={values.overdue === "true"} onChange={e => setFilter("overdue", e.target.checked ? "true" : "")} /> Overdue customers only</label> : null}
        <div className="receivables-sort">
        <Field label="Sort by"><Select value={values.sort || "amount"} options={[{ value: "amount", label: "Amount" }, { value: "name", label: "Name" }]} onChange={e => setFilter("sort", e.target.value)} /></Field>
        <Field label="Order"><Select value={values.direction || "desc"} options={[{ value: "desc", label: "Descending" }, { value: "asc", label: "Ascending" }]} onChange={e => setFilter("direction", e.target.value)} /></Field>
        </div>
        <Button variant="secondary" onClick={() => { setFilters(Object.fromEntries(FILTERS.filter(k => k !== "type" && k !== "merchant").map(k => [k, ""]))); setCustomer(null); }}>Reset filters</Button>
      </div>
      <p className="receivables-help">{collection ? "Payments received in the selected period, using their current verification status. Blank dates default to the last 30 days. Applied amounts reduce invoice dues; pending submissions are shown separately." : "Current unpaid invoice balances across all invoice dates. Due today is not overdue. Aging uses the invoice due date in India time."} Groups reflect current membership.</p>
      {values.customer ? <Button variant="secondary" onClick={() => setFilter("customer", "")}>Clear selected customer</Button> : null}
    </Card>
    {groups.isError ? <ErrorState error={groups.error} onRetry={() => void groups.refetch()} /> : null}
    {enabled && report.isError ? <Card><ErrorState error={report.error} onRetry={() => void report.refetch()} /></Card> : null}
    {enabled && report.data ? <>
      <div className="receivables-summary" aria-label="Report summary">{report.data.summary.map(item => <div key={item.label} className="stat-card"><span className="stat-card__label">{item.label}</span><strong className="stat-card__value">{formatReportFigure(item.label, item.value)}</strong></div>)}</div>
      <p className="text-muted">{collection ? `${formatDateTime(report.data.period.from)} – ${formatDateTime(report.data.period.to)}` : "Current balances"} · Generated {formatDateTime(report.data.generatedAt)}</p>
    </> : null}
    <Card bodyless><DataTable caption={collection ? "Collections" : "Outstanding dues"} columns={reportColumns} rows={enabled ? report.data?.rows : []} getRowKey={row => String(row.id)} onRowClick={open} isLoading={enabled && report.isLoading}
      empty={<EmptyState title="No matching customers" description="Change the filters to view other customers." />} footer={<Pagination page={page} pageSize={PAGE_SIZE} total={Number(report.data?.metadata?.total || 0)} onPageChange={setPage} itemLabel={groupBy === "group" ? "groups" : "customers"} />} /></Card>
    {manageGroups && merchantId ? <CustomerReportGroups key={merchantId} merchantId={merchantId} groups={groups.data || []} onClose={() => setManageGroups(false)} /> : null}
    {customer ? <Drawer open size="lg" title={String(customer.customer)} subtitle={collection ? "Payment receipts and invoice allocations" : "Current unpaid invoices and their payment history"} onClose={() => { setCustomer(null); setDetails(null); }}>
      <DataTable caption={collection ? "Receipts" : "Unpaid invoices"} columns={columnsFor(detailColumns, row => setDetails(row._details as ReportRowDetails), collection ? "paidAt" : "invoice")} rows={detail.data?.rows} getRowKey={row => String(row.id)} isLoading={detail.isLoading} error={detail.error} onRetry={() => void detail.refetch()}
        empty={<EmptyState title="No records" />} footer={<Pagination page={detailPage} pageSize={PAGE_SIZE} total={detail.data?.total || 0} onPageChange={setDetailPage} itemLabel="records" />} />
    </Drawer> : null}
    {details ? <ReportRowDrawer details={details} onClose={() => setDetails(null)} /> : null}
  </div>;
}
