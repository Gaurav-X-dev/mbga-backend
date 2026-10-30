import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { normalizeError } from "../../api/errors";
import { listCustomers } from "../../api/customers.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { exportReport, getReport, type ExportFormat, type ReportColumn, type ReportParams, type ReportType } from "../../api/reports.api";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Icon, type IconName } from "../../components/common/Icon";
import { EmptyState, ErrorState, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { StatusBadge } from "../../components/common/StatusBadge";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatDateTime, todayInputValue } from "../../utils/format";
import { cylinderLabel, formatReportFigure } from "./report-format";
import { downloadCsv } from "../../utils/csv";
import { humanize } from "../../utils/format";
import { ReportRowDrawer, type ReportRowDetails } from "./ReportRowDrawer";
import { expenseToday } from "../admin-expenses/expense-utils";
import { FuelReportFilters, FUEL_FILTER_KEYS } from "./FuelReportFilters";
import { StockRegister } from "./StockRegister";

const PAGE_SIZE = 25;
const FILTERS = ["type", "merchant", "customer", "range", "from", "to", "q", "view", ...FUEL_FILTER_KEYS] as const;

const REPORTS: Array<{ type: ReportType; label: string; description: string; icon: IconName }> = [
  { type: "DAILY_DELIVERY", label: "Daily deliveries", description: "Cylinders delivered, day by day", icon: "truck" },
  { type: "PAYMENT_COLLECTION", label: "Payment collection", description: "Money collected, by mode", icon: "wallet" },
  { type: "PENDING_PICKUP", label: "Pending pickups", description: "Empties still with customers", icon: "refresh" },
  { type: "FUEL", label: "Fuel sheet", description: "Vehicle fuel, distance and mileage register", icon: "flame" },
  { type: "EXPENSE", label: "Expenses", description: "Spend by category", icon: "fileText" },
  { type: "STOCK_MOVEMENT", label: "Stock movement", description: "Godown ins and outs", icon: "box" },
  { type: "PROFIT_LOSS", label: "Profit & loss", description: "Revenue less costs", icon: "trendingUp" },
  { type: "TAX_GST", label: "GST / tax", description: "Tax collected for filing", icon: "chart" }
];

const RANGES = [
  { value: "all", label: "All time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "month", label: "This month" },
  { value: "lastMonth", label: "Last month" },
  { value: "custom", label: "Custom" }
] as const;

/** "VIEW" exports exactly what is on screen, including the per-cylinder columns the server export lacks. */
type ExportChoice = ExportFormat | "VIEW";

const EXPORTS: Array<{ value: ExportChoice; label: string }> = [
  { value: "VIEW", label: "This view (CSV, as shown)" },
  { value: "XLSX", label: "Excel (.xlsx)" },
  { value: "CSV", label: "CSV" },
  { value: "JSON", label: "JSON" },
  { value: "XML", label: "XML" }
];

function iso(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Reports about customers. Stock, expenses and P&L are godown or business-wide, so no customer filter. */
const CUSTOMER_REPORTS: ReportType[] = ["DAILY_DELIVERY", "PAYMENT_COLLECTION", "PENDING_PICKUP", "TAX_GST"];

/** Earlier than any record the platform can hold. */
const ALL_TIME_FROM = "2020-01-01";

/** Fields a row may carry its date in, in order of preference, when the report has no date column. */
const ROW_DATE_KEYS = ["date", "scheduledDate", "deliveryDate", "paidAt", "issuedAt", "recordedAt", "createdAt", "spendDate"];

/** Resolves a preset to inclusive local dates; "all" has none, so every record is returned. */
function resolveRange(range: string, from: string, to: string, businessDay?: string): { from: string; to: string } | null {
  const today = businessDay ? new Date(`${businessDay}T12:00:00`) : new Date();
  const daysAgo = (n: number) => iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - n));
  switch (range) {
    case "all":
      // Without dates the backend falls back to the last 7 days, so "all" asks from the start.
      return { from: ALL_TIME_FROM, to: iso(today) };
    case "today":
      return { from: iso(today), to: iso(today) };
    case "30d":
      return { from: daysAgo(29), to: iso(today) };
    case "month":
      return { from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) };
    case "lastMonth":
      return {
        from: iso(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
        to: iso(new Date(today.getFullYear(), today.getMonth(), 0))
      };
    case "custom":
      return { from: from || daysAgo(6), to: to || iso(today) };
    default:
      return { from: daysAgo(6), to: iso(today) };
  }
}

function formatCell(column: ReportColumn, value: unknown) {
  if (value === null || value === undefined || value === "") return <span className="text-muted">—</span>;
  // Column labels are the readable form ("Tax invoices"); keys are a fallback.
  if (typeof value === "number") return formatReportFigure(`${column.label} ${column.key}`, value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T|$)/.test(value)) return value.length > 10 ? formatDateTime(value) : formatDate(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function AdminReportsPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = isMerchantPanel ? "Business Reports" : "Reports"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const { values, page, setFilter, setFilters, setPage } = useUrlFilters(FILTERS);
  const type = (REPORTS.find((r) => r.type === values.type)?.type ?? "DAILY_DELIVERY") as ReportType;
  // Opens on everything the backend has, so existing records show straight away.
  const range = values.range || "all";
  const dates = resolveRange(range, values.from, values.to, type === "FUEL" ? expenseToday() : undefined);
  const [exportFormat, setExportFormat] = useState<ExportChoice>("VIEW");

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: !isMerchantPanel,
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id;
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId || "" : values.merchant);

  const datesValid = !dates || dates.from <= dates.to;
  // Whole days in IST, which is where the business runs. No dates = all time.
  const params: ReportParams = {
    type,
    ...(type === "FUEL" ? {...Object.fromEntries(FUEL_FILTER_KEYS.map((key) => [key, values[key] || undefined])), search: values.q || undefined} : {}),
    allTime: type === "FUEL" && range === "all" ? true : undefined,
    from: type === "FUEL" && range === "all" ? undefined : dates ? `${dates.from}T00:00:00+05:30` : undefined,
    to: type === "FUEL" && range === "all" ? undefined : dates ? `${dates.to}T23:59:59+05:30` : undefined,
    merchantId: merchantId || undefined,
    // A customer chosen on another report is ignored here rather than silently filtering this one.
    customerId: CUSTOMER_REPORTS.includes(type) ? values.customer || undefined : undefined
  };
  const report = useQuery({
    queryKey: queryKeys.reports.detail(params),
    queryFn: ({ signal }) => getReport(params, signal),
    enabled: datesValid && (!isMerchantPanel || Boolean(merchantId)),
    placeholderData: keepPreviousData
  });

  const exporter = useMutation({
    mutationFn: () => exportReport(params, exportFormat as ExportFormat),
    onSuccess: (filename) => toast.success(`Downloaded ${filename}.`),
    onError: (error) => toast.error(normalizeError(error).userMessage)
  });

  const data = type === "FUEL" && report.data?.type !== "FUEL" ? undefined : report.data;
  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const q = values.q.trim().toLowerCase();
    if (!q || type === "FUEL") return all;
    return all.filter((row) => Object.values(row).some((v) => v !== null && v !== undefined && String(v).toLowerCase().includes(q)));
  }, [data, values.q, type]);

  // Customer filter options. The report itself lists who appears in the period (any merchant);
  // with a merchant chosen, its full customer list is merged in. The unfiltered report is
  // requested with the same key the page already cached, so this costs nothing extra.
  const unfilteredParams: ReportParams = { ...params, customerId: undefined };
  const unfiltered = useQuery({
    queryKey: queryKeys.reports.detail(unfilteredParams),
    queryFn: ({ signal }) => getReport(unfilteredParams, signal),
    enabled: datesValid && Boolean(values.customer),
    staleTime: 60_000
  });
  const merchantCustomerParams = { merchantId: values.merchant, customerType: "ALL", accountStatus: "ALL", limit: 100, offset: 0 };
  const merchantCustomers = useQuery({
    queryKey: queryKeys.customers.list(merchantCustomerParams),
    queryFn: ({ signal }) => listCustomers(merchantCustomerParams, signal),
    enabled: Boolean(values.merchant) && CUSTOMER_REPORTS.includes(type),
    staleTime: 5 * 60_000,
    retry: false
  });
  const customerOptions = useMemo(() => {
    const byId = new Map<string, string>();
    const source = values.customer ? unfiltered.data?.rows : data?.rows;
    for (const row of source ?? []) {
      const id = row.customerId;
      const name = row.customer ?? row.customerName;
      if (typeof id === "string" && typeof name === "string") byId.set(id, name);
    }
    for (const c of merchantCustomers.data?.items ?? []) byId.set(c.id, c.businessName || c.ownerName || c.mobile);
    return [...byId.entries()]
      .map(([value, label]) => ({ value, label: label.length > 48 ? `${label.slice(0, 47)}…` : label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [data, unfiltered.data, merchantCustomers.data, values.customer]);

  // Quantity per cylinder type, from each row's breakdown. Types are listed smallest first.
  const qtyByType = (row: Record<string, unknown>) => {
    const lines = ((row._details as ReportRowDetails | undefined)?.breakdown ?? []) as NonNullable<ReportRowDetails["breakdown"]>;
    const map = new Map<string, number>();
    for (const line of lines) map.set(line.title, (map.get(line.title) ?? 0) + (line.quantity ?? 0));
    return map;
  };
  const weight = (code: string) => Number.parseFloat(cylinderLabel(code)) || Number.MAX_SAFE_INTEGER;
  const cylinderTypes = useMemo(() => {
    const totals = new Map<string, number>();
    for (const row of rows) for (const [type, qty] of qtyByType(row)) totals.set(type, (totals.get(type) ?? 0) + qty);
    return [...totals.entries()].filter(([, qty]) => qty > 0).sort((a, b) => weight(a[0]) - weight(b[0]));
  }, [rows]);

  // Rows often carry a date (scheduledDate, paidAt…) that the report's columns leave out.
  // Show it as the first column, because "when" is the first thing a report is read by.
  const reportColumns = data?.columns ?? [];
  const dateKey =
    reportColumns.some((c) => /date|day|time|at$/i.test(c.key))
      ? null
      : (ROW_DATE_KEYS.find((key) => (data?.rows ?? []).some((row) => typeof row[key] === "string")) ?? null);
  const allColumns: ReportColumn[] = dateKey ? [{ key: dateKey, label: "Date", align: "left" }, ...reportColumns] : reportColumns;

  const columns: Column<Record<string, unknown>>[] = allColumns.map((column, index) => ({
    key: column.key,
    header: column.label,
    primary: index === 0,
    align: column.align,
    sortValue: (row) => {
      const value = row[column.key];
      return typeof value === "number" || typeof value === "string" ? value : null;
    },
    render: (row) => {
      const value = row[column.key];
      if (/status/i.test(column.key) && typeof value === "string") return <StatusBadge status={value} />;
      if (typeof value === "string" && value.length > 32 && !/^\d{4}-\d{2}-\d{2}/.test(value)) {
        return (
          <span title={value} style={{ display: "block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {value}
          </span>
        );
      }
      return <span className="nowrap">{formatCell(column, value)}</span>;
    }
  }));
  for (const [type] of cylinderTypes) {
    columns.push({
      key: `cyl:${type}`,
      header: cylinderLabel(type),
      align: "right",
      hideOnMobile: true,
      sortValue: (row) => qtyByType(row).get(type) ?? 0,
      render: (row) => {
        const qty = qtyByType(row).get(type) ?? 0;
        return qty ? <strong>{qty}</strong> : <span className="text-muted">—</span>;
      }
    });
  }

  /** Plain-text form of a cell, for the CSV - the same formatting the table uses, minus markup. */
  function cellText(column: ReportColumn, value: unknown): string {
    if (value === null || value === undefined || value === "") return "";
    if (/status/i.test(column.key) && typeof value === "string") return humanize(value);
    if (typeof value === "number") return formatReportFigure(`${column.label} ${column.key}`, value).replace(/₹\s?/g, "").replace(/,/g, "");
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T|$)/.test(value)) return value.length > 10 ? formatDateTime(value) : formatDate(value);
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function exportView() {
    if (!data) return;
    const header = [...allColumns.map((c) => c.label), ...cylinderTypes.map(([type]) => cylinderLabel(type))];
    const body = rows.map((row) => [
      ...allColumns.map((c) => cellText(c, row[c.key])),
      ...cylinderTypes.map(([type]) => qtyByType(row).get(type) ?? 0)
    ]);
    if (cylinderTypes.length) {
      body.push([]);
      body.push(["Total", ...allColumns.slice(1).map(() => ""), ...cylinderTypes.map(([, qty]) => qty)]);
    }
    const customer = params.customerId ? customerOptions.find((o) => o.value === params.customerId)?.label : undefined;
    const stamp = range === "all" ? "all-time" : `${dates?.from ?? ""}_${dates?.to ?? ""}`;
    const slug = (customer ?? merchantName ?? "all").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "all";
    downloadCsv(`${type.toLowerCase()}-${slug}-${stamp}.csv`, header, body);
    toast.success(`Exported ${rows.length} rows.`);
  }

  const [openDetails, setOpenDetails] = useState<ReportRowDetails | null>(null);

  const merchantName = merchants.data?.items.find((m) => m.id === values.merchant)?.business_name;
  const meta = REPORTS.find((r) => r.type === type)!;

  return (
    <div className="page admin-reports-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Agency business reports and analytics. Export any report for accounts, compliance or filing." : "Platform reports across every merchant, or one at a time. Export any report for accounts or filing."}
        meta={<RefreshIndicator active={report.isFetching && !report.isLoading} />}
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={values.merchant}
                  onChange={(event) => setFilters({ merchant: event.target.value, customer: "" })}
                  placeholder="All merchants"
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            {CUSTOMER_REPORTS.includes(type) ? (
            <Field label="Customer" hideLabel>
              <Select
                value={values.customer}
                onChange={(event) => setFilter("customer", event.target.value)}
                placeholder={customerOptions.length || values.customer ? "All customers" : "No customers in period"}
                disabled={!customerOptions.length && !values.customer}
                options={customerOptions}
                title="Customers who appear in this report, plus every customer of the selected merchant"
              />
            </Field>
            ) : null}
            <Field label="Export format" hideLabel>
              <Select value={exportFormat} onChange={(event) => setExportFormat(event.target.value as ExportChoice)} options={EXPORTS} />
            </Field>
            <Button icon="download" onClick={() => (exportFormat === "VIEW" ? exportView() : exporter.mutate())} loading={exporter.isPending} loadingText="Exporting…" disabled={!datesValid || (type === "FUEL" && (report.isFetching || report.isError || !data || (auth ? !auth.can("reports.export") : false)))}>
              Export
            </Button>
          </>
        }
      />

      <div
        role="tablist"
        aria-label="Report type"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: "var(--space-3)" }}
      >
        {REPORTS.map((item) => {
          const active = item.type === type;
          return (
            <button
              key={item.type}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setFilters({ type: item.type, q: "" })}
              className="card"
              style={{
                textAlign: "left",
                padding: "var(--space-4)",
                cursor: "pointer",
                borderColor: active ? "var(--blue-500, #3b82f6)" : undefined,
                boxShadow: active ? "0 0 0 2px var(--blue-500, #3b82f6) inset" : undefined
              }}
            >
              <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                <span className={`mini-stat__icon ${active ? "tone-blue" : "tone-slate"}`} aria-hidden="true">
                  <Icon name={item.icon} size={16} />
                </span>
                <strong>{item.label}</strong>
              </span>
              <small className="text-muted" style={{ display: "block", marginTop: 6 }}>
                {item.description}
              </small>
            </button>
          );
        })}
      </div>

      <Card bodyless>
        <div className="row" style={{ gap: "var(--space-3)", padding: "var(--space-4)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="status-tabs" role="tablist" aria-label="Date range" style={{ border: 0 }}>
            {RANGES.map((item) => (
              <button
                key={item.value}
                type="button"
                role="tab"
                aria-selected={range === item.value}
                onClick={() =>
                  item.value === "custom"
                    ? setFilters({ range: "custom", from: dates?.from ?? todayInputValue(), to: dates?.to ?? todayInputValue() })
                    : setFilters({ range: item.value === "all" ? "" : item.value, from: "", to: "" })
                }
              >
                {item.label}
              </button>
            ))}
          </div>
          {range === "custom" && dates ? (
            <>
              <Field label="From">
                <Input type="date" max={todayInputValue()} value={dates.from} onChange={(e) => setFilter("from", e.target.value)} />
              </Field>
              <Field label="To" error={datesValid ? undefined : "Must be on or after From."}>
                <Input type="date" max={todayInputValue()} value={dates.to} onChange={(e) => setFilter("to", e.target.value)} />
              </Field>
            </>
          ) : (
            <span className="text-muted text-small">{range === "all" ? "Every record on file" : dates ? `${formatDate(dates.from)} – ${formatDate(dates.to)}` : null}</span>
          )}
        </div>
      </Card>

      {type === "FUEL" ? <FuelReportFilters values={values}
        metadata={data?.metadata} onChange={(key, value) => setFilter(key as typeof FILTERS[number], value)}
        onReset={() => setFilters(Object.fromEntries([...FUEL_FILTER_KEYS, "q"].map((key) => [key, ""])))} /> : null}

      {report.isLoading ? (
        <LoadingSkeleton rows={8} label="Building report" />
      ) : report.error && !data ? (
        <Card>
          <ErrorState error={report.error} onRetry={() => void report.refetch()} />
        </Card>
      ) : data ? (
        <>
          {data.summary.length ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--space-4)" }} aria-label="Report summary">
              {data.summary.map((item) => (
                <div key={item.label} className="stat-card">
                  <span className="stat-card__label">{item.label}</span>
                  <span className="stat-card__value" style={{ fontSize: "1.5rem" }}>
                    {formatReportFigure(item.label, item.value)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {type === "STOCK_MOVEMENT" ? (
            <div className="status-tabs" role="tablist" aria-label="Stock movement view" style={{ border: 0 }}>
              <button type="button" role="tab" aria-selected={values.view !== "list"} onClick={() => setFilter("view", "")}>
                Register (day-wise)
              </button>
              <button type="button" role="tab" aria-selected={values.view === "list"} onClick={() => setFilter("view", "list")}>
                All movements
              </button>
            </div>
          ) : null}

          {type === "STOCK_MOVEMENT" && values.view !== "list" ? (
            <StockRegister rows={rows} merchantId={values.merchant || undefined} periodFrom={params.from!} periodTo={dates?.to} merchantName={merchantName} />
          ) : (
            <>
          {cylinderTypes.length ? (
            <Card title="Cylinders by type" subtitle={`Across ${rows.length} ${rows.length === 1 ? "row" : "rows"}${values.q ? " matching the search" : ""}`}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "var(--space-3)" }}>
                {cylinderTypes.map(([type, qty]) => (
                  <div key={type} className="mini-stat">
                    <span className="mini-stat__icon tone-blue" aria-hidden="true">
                      <Icon name="box" size={16} />
                    </span>
                    <span className="mini-stat__text">
                      <strong>{qty}</strong>
                      <span>{cylinderLabel(type)}</span>
                    </span>
                  </div>
                ))}
                <div className="mini-stat">
                  <span className="mini-stat__icon tone-green" aria-hidden="true">
                    <Icon name="checkCircle" size={16} />
                  </span>
                  <span className="mini-stat__text">
                    <strong>{cylinderTypes.reduce((sum, [, qty]) => sum + qty, 0)}</strong>
                    <span>Total cylinders</span>
                  </span>
                </div>
              </div>
            </Card>
          ) : null}

          <Card bodyless className="table-card">
            <TableHeader
              title={data.title || meta.label}
              count={rows.length}
              description={`${merchantName ?? "All merchants"}${params.customerId ? ` · ${customerOptions.find((o) => o.value === values.customer)?.label ?? "1 customer"}` : ""} · ${range === "all" ? "All time" : `${formatDate(data.period.from)} – ${formatDate(data.period.to)}`} · generated ${formatDateTime(data.generatedAt)}`}
              actions={
                <Button variant="secondary" size="sm" icon="refresh" onClick={() => void report.refetch()} disabled={report.isFetching}>
                  Refresh
                </Button>
              }
            />
            {data.rows.length > 0 && type !== "FUEL" ? (
              <FilterBar onReset={() => setFilter("q", "")} canReset={Boolean(values.q)}>
                <SearchInput label="Search rows" placeholder="Filter rows in this report" value={values.q} onChange={(e) => setFilter("q", e.target.value)} />
              </FilterBar>
            ) : null}
            <DataTable
              caption={data.title || meta.label}
              columns={columns}
              rows={rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)}
              getRowKey={(row) => String(row.id ?? JSON.stringify(row))}
              onRowClick={(row) => {
                const details = row._details as ReportRowDetails | undefined;
                if (details) setOpenDetails(details);
              }}
              rowLabel={(row) => String(row.displayId ?? row.id ?? "row")}
              isLoading={false}
              empty={
                values.q ? (
                  <EmptyState icon="search" title="No rows match" description="Try a different search." />
                ) : (
                  <EmptyState
                    icon={meta.icon}
                    title={range === "all" ? "No records yet" : "Nothing in this period"}
                    description={range === "all" ? "Nothing has been recorded for this report yet." : "There are no records in this date range."}
                    action={
                      range === "all" ? undefined : (
                        <Button variant="secondary" onClick={() => setFilters({ range: "", from: "", to: "" })}>
                          Show all time
                        </Button>
                      )
                    }
                  />
                )
              }
              footer={<Pagination page={page} pageSize={PAGE_SIZE} total={rows.length} onPageChange={setPage} itemLabel="rows" />}
            />
          </Card>
            </>
          )}
        </>
      ) : null}
      {openDetails ? <ReportRowDrawer details={openDetails} onClose={() => setOpenDetails(null)} /> : null}
    </div>
  );
}

export default AdminReportsPage;
