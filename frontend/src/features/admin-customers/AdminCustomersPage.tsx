import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listCustomers, listCustomerEmployees, type Customer } from "../../api/customers.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatDate, formatRelativeTime, humanize } from "../../utils/format";
import { downloadCsv } from "../../utils/csv";
import { customerReport } from "./customer-report";
import { AddCustomerDialog } from "./AddCustomerDialog";
import { customerName } from "./customer-utils";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "type", "status", "search", "employee", "dateFrom", "dateTo", "gstStatus"] as const;

const TYPE_TABS = [
  { value: "ALL", label: "All customers" },
  { value: "RETAIL", label: "Retail" },
  { value: "INDUSTRIAL", label: "Industrial" }
];

const STATUS_OPTIONS = ["ACTIVE", "PENDING_APPROVAL", "REJECTED", "SUSPENDED", "BLOCKED"].map((value) => ({
  value,
  label: humanize(value)
}));

const TRUNCATE = { display: "block", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;

export function AdminCustomersPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = isMerchantPanel ? "Customer Accounts" : "Customers"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage, clearFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const type = values.type || "ALL";
  const [adding, setAdding] = useState(false);

  // Customers belong to a merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  const [reportOption, setReportOption] = useState("customers");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);
  const invalidRange = Boolean(values.dateFrom && values.dateTo && values.dateFrom > values.dateTo);
  const employees = useQuery({
    queryKey: ["customer-employees", merchantId],
    queryFn: ({ signal }) => listCustomerEmployees(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 60_000
  });

  const params = {
    employee: values.employee || undefined,
    dateFrom: values.dateFrom || undefined,
    dateTo: values.dateTo || undefined,
    merchantId,
    customerType: type,
    accountStatus: values.status || "ALL",
    gstStatus: (["GST", "NON_GST"].includes(values.gstStatus) ? values.gstStatus : "ALL") as "ALL" | "GST" | "NON_GST",
    search: values.search || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.customers.list(params),
    queryFn: ({ signal }) => listCustomers(params, signal),
    enabled: Boolean(merchantId) && !invalidRange,
    placeholderData: keepPreviousData
  });

  const detailHref = (customer: Customer) =>
    isMerchantPanel
      ? `/merchant/customers/${encodeURIComponent(customer.id)}`
      : `/admin/customer-accounts/${encodeURIComponent(customer.id)}?merchant=${encodeURIComponent(merchantId)}`;
  const filtered = Boolean(values.gstStatus || values.status || values.search || values.employee || values.dateFrom || values.dateTo);

  async function exportReport() {
    setExporting(true);
    setExportError(null);
    try {
      const rows: Customer[] = [];
      let offset = 0;
      while (true) {
        const result = await listCustomers({ ...params, limit: 100, offset });
        rows.push(...result.items);
        offset += result.items.length;
        if (offset >= result.total) break;
        if (!result.items.length) throw new Error("Customer list changed. Please retry the export.");
      }
      const report = customerReport(rows, reportOption);
      downloadCsv(`customer-${reportOption}-report.csv`, report.header, report.rows);
      toast.success(`${rows.length} customers exported.`);
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  }

  const columns: Column<Customer>[] = [
    {
      key: "customer",
      header: "Customer",
      primary: true,
      sortValue: (c) => customerName(c),
      render: (c) => (
        <div className="cell-primary">
          <UserAvatar name={customerName(c)} />
          <div className="cell-primary__text">
            <Link to={detailHref(c)} className="cell-primary__title" style={TRUNCATE} title={customerName(c)}>
              {customerName(c)}
            </Link>
            <span className="cell-primary__subtitle nowrap">
              {c.code ? <span className="mono">{c.code}</span> : null}
              {c.code && c.customerType ? " · " : ""}
              {c.customerType ? humanize(c.customerType) : ""}
            </span>
          </div>
        </div>
      )
    },
    {
      key: "contact",
      header: "Contact",
      render: (c) => (
        <div className="cell-stack">
          <span className="nowrap">{c.mobile}</span>
          <small style={TRUNCATE}>{c.ownerName && c.businessName ? c.ownerName : c.deliveryAddress?.city || "—"}</small>
        </div>
      )
    },
    {
      key: "gst",
      header: "GST",
      render: (c) => c.gstin?.trim() ? (
        <div className="cell-stack">
          <span className="badge">GST</span>
          <small className="mono nowrap">{c.gstin.trim()}</small>
        </div>
      ) : <span className="badge">Non-GST</span>
    },
    { key: "employee", header: "Employee", render: (c) => c.employeeName || c.employeeId || "Not recorded" },
    { key: "registered", header: "Registered", render: (c) => c.registeredAt ? formatDate(c.registeredAt) : "—" },
    { key: "kyc", header: "KYC", sortValue: (c) => c.kycStatus, render: (c) => <StatusBadge status={c.kycStatus} /> },
    {
      key: "balance",
      header: "Balance",
      align: "right",
      sortValue: (c) => c.runningBalance,
      render: (c) => (
        <strong className="nowrap" style={c.runningBalance > 0 ? { color: "var(--red-600, #dc2626)" } : undefined}>
          {formatCurrency(c.runningBalance)}
        </strong>
      )
    },
    {
      key: "lastOrder",
      header: "Last order",
      hideOnMobile: true,
      sortValue: (c) => c.lastOrderAt ?? "",
      render: (c) =>
        c.lastOrderAt ? (
          <div className="cell-stack">
            <span className="nowrap">{formatDate(c.lastOrderAt)}</span>
            <small className="nowrap">{formatRelativeTime(c.lastOrderAt)}</small>
          </div>
        ) : (
          <span className="text-muted">Never</span>
        )
    },
    { key: "status", header: "Account", sortValue: (c) => c.accountStatus, render: (c) => <StatusBadge status={c.accountStatus} /> }
  ];

  return (
    <div className="page admin-customers-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Customer directory: accounts, KYC status, cylinder quota and running balance." : "Every customer of a merchant: account, KYC, balance and pricing."}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => setFilter("merchant", event.target.value)}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            <Button icon="userPlus" onClick={() => setAdding(true)} disabled={!merchantId}>
              Add customer
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
            <EmptyState icon="store" title="Choose a merchant" description="Customers belong to a merchant. Pick one above." />
          </Card>
        )
      ) : (
        <Card bodyless className="table-card">
          <div className="status-tabs status-tabs--card" role="tablist" aria-label="Customer type">
            {TYPE_TABS.map((item) => (
              <button key={item.value} type="button" role="tab" aria-selected={type === item.value} onClick={() => setFilter("type", item.value === "ALL" ? "" : item.value)}>
                {item.label}
              </button>
            ))}
          </div>
          <TableHeader title={TYPE_TABS.find((t) => t.value === type)?.label ?? "Customers"} count={query.data?.total} description="Select a customer to see their account, orders and pricing." />
          <FilterBar onReset={() => clearFilters(["status", "search", "employee", "dateFrom", "dateTo", "gstStatus"])} canReset={filtered}>
            <SearchInput label="Search customers" placeholder="Business, owner, mobile or code" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
            <Field label="Account status" hideLabel>
              <Select value={values.status} onChange={(e) => setFilter("status", e.target.value)} placeholder="Any status" options={STATUS_OPTIONS} />
            </Field>
            <Field label="GST Status">
              <Select value={values.gstStatus} onChange={(e) => setFilter("gstStatus", e.target.value)}
                placeholder="All customers" options={[
                  { value: "GST", label: "GST customers" },
                  { value: "NON_GST", label: "Non-GST customers" }
                ]} />
            </Field>
            <Field label="Employee">
              <Select value={values.employee} onChange={(e) => setFilter("employee", e.target.value)}
                placeholder={employees.isLoading ? "Loading employees…" : "All employees"}
                options={employees.data ?? []} disabled={employees.isLoading || exporting} />
            </Field>
            <Field label="From date">
              <Input type="date" value={values.dateFrom} max={values.dateTo || undefined}
                onChange={(e) => setFilter("dateFrom", e.target.value)} disabled={exporting} />
            </Field>
            <Field label="To date" error={invalidRange ? "End date must be on or after start date." : undefined}>
              <Input type="date" value={values.dateTo} min={values.dateFrom || undefined}
                onChange={(e) => setFilter("dateTo", e.target.value)} disabled={exporting} />
            </Field>
          </FilterBar>
          <div className="row" style={{ padding: "var(--space-4)", flexWrap: "wrap", alignItems: "flex-end" }}>
            <Field label="Report options">
              <Select value={reportOption} onChange={(e) => setReportOption(e.target.value)} disabled={exporting}
                options={[
                  { value: "customers", label: "Customer records (CSV)" },
                  { value: "employees", label: "Employee productivity (CSV)" },
                  { value: "daily", label: "Daily acquisition (CSV)" }
                ]} />
            </Field>
            <Button onClick={() => void exportReport()} loading={exporting} loadingText="Exporting…"
              disabled={invalidRange || query.isFetching || !query.data?.total}>Export report</Button>
          </div>
          {employees.error ? <InlineError error={employees.error} title="Employee options could not be loaded" onRetry={() => void employees.refetch()} /> : null}
          {exportError ? <InlineError error={exportError} title="Report could not be exported" onRetry={() => void exportReport()} /> : null}


          {query.error && query.data ? (
            <div style={{ padding: "var(--space-4)" }}>
              <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
            </div>
          ) : null}

          <DataTable
            caption="Customers"
            columns={columns}
            rows={invalidRange ? [] : query.data?.items}
            getRowKey={(c) => c.id}
            getRowHref={detailHref}
            rowLabel={(c) => customerName(c)}
            rowActions={(c) => [{ label: "Open customer", icon: "eye", onSelect: () => navigate(detailHref(c)) }]}
            isLoading={query.isLoading}
            error={query.data ? undefined : query.error}
            onRetry={() => void query.refetch()}
            empty={
              filtered ? (
                <EmptyState icon="search" title="No customers match" description="Try a different GST status, employee, date range, name, mobile or account status." />
              ) : (
                <EmptyState
                  icon="users"
                  title="No customers yet"
                  description="Customers register from the app, or can be added here."
                  action={<Button icon="userPlus" onClick={() => setAdding(true)}>Add customer</Button>}
                />
              )
            }
            footer={<Pagination page={page} pageSize={PAGE_SIZE} total={query.data?.total ?? 0} onPageChange={setPage} itemLabel="customers" disabled={query.isFetching} />}
          />
        </Card>
      )}

      {merchantId ? (
        <AddCustomerDialog
          open={adding}
          merchantId={merchantId}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            toast.success(`${customerName(created)} added and sent for KYC review.`);
            void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.customerKyc.all });
            navigate(detailHref(created));
          }}
        />
      ) : null}
    </div>
  );
}

export default AdminCustomersPage;
