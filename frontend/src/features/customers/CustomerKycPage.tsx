import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { getKycStats, listKycApplications, type KycApplicationSummary } from "../../api/customer-kyc.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatDateTime, formatNumber, formatRelativeTime } from "../../utils/format";
import { statusMeta } from "../../utils/labels";
import { DocumentProgress } from "./DocumentProgress";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "merchant"] as const;

const TABS = [
  { value: "PENDING", label: "Pending Review" },
  { value: "APPROVED", label: "Approved" },
  { value: "REJECTED", label: "Rejected" },
  { value: "ALL", label: "All" }
] as const;

const EMPTY_BY_TAB: Record<string, { title: string; description: string }> = {
  PENDING: {
    title: "No KYC requests pending",
    description: "New customer registrations will appear here for review."
  },
  APPROVED: { title: "No approved applications", description: "Approved customers will appear here." },
  REJECTED: { title: "No rejected applications", description: "Rejected applications will appear here." },
  ALL: { title: "No applications yet", description: "Customer registrations will appear here once they are submitted." }
};

export function CustomerKycPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const tab = values.status || "PENDING";

  const params = {
    status: tab,
    merchant_id: values.merchant || undefined,
    search: values.search || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.customerKyc.list(params),
    queryFn: ({ signal }) => listKycApplications(params, signal),
    placeholderData: keepPreviousData
  });
  const stats = useQuery({
    queryKey: queryKeys.customerKyc.stats(),
    queryFn: ({ signal }) => getKycStats(signal),
    staleTime: 60_000,
    retry: false
  });
  // The merchant filter's options. Failures stay quiet; the filter simply stays empty.
  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: auth.can(PERMISSIONS.merchantsView),
    staleTime: 5 * 60_000,
    retry: false
  });

  const columns: Column<KycApplicationSummary>[] = [
    {
      key: "customer",
      header: "Customer",
      primary: true,
      sortValue: (item) => item.customer_name ?? "",
      render: (item) => (
        <div className="cell-primary">
          <UserAvatar name={item.customer_name} />
          <div className="cell-primary__text">
            <Link to={`/admin/customers/${item.id}`} className="cell-primary__title">
              {item.customer_name ?? "Unnamed customer"}
            </Link>
            <span className="cell-primary__subtitle">{item.customer_type ?? "Customer"}</span>
          </div>
        </div>
      )
    },
    {
      key: "mobile",
      header: "Mobile",
      render: (item) => <span className="nowrap">{item.customer_mobile ?? "—"}</span>
    },
    {
      key: "merchant",
      header: "Merchant",
      sortValue: (item) => item.merchant_name ?? "",
      render: (item) => (
        <div className="cell-stack">
          <span>{item.merchant_name ?? "Unassigned"}</span>
          {item.city ? <small>{item.city}</small> : null}
        </div>
      )
    },
    {
      key: "documents",
      header: "Documents",
      render: (item) => (
        <DocumentProgress verified={item.verified_document_count} total={item.document_count} />
      )
    },
    {
      key: "submitted",
      header: "Submitted on",
      sortValue: (item) => item.submitted_at,
      render: (item) => (
        <time dateTime={item.submitted_at} title={formatDateTime(item.submitted_at)} className="cell-stack">
          <span className="nowrap">{formatDate(item.submitted_at)}</span>
          <small>{formatRelativeTime(item.submitted_at)}</small>
        </time>
      )
    },
    { key: "status", header: "Status", sortValue: (item) => item.status, render: (item) => <StatusBadge status={item.status} /> }
  ];

  const empty = EMPTY_BY_TAB[tab] ?? EMPTY_BY_TAB.ALL;

  return (
    <div className="page customer-kyc-page">
      <PageHeader
        title="Customer KYC"
        documentTitle="Customer KYC"
        description="Review customer registrations and document verification status across every merchant."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <Button variant="secondary" icon="refresh" onClick={() => void query.refetch()} disabled={query.isFetching}>
            Refresh
          </Button>
        }
      />

      <div className="kpi-grid" aria-label="KYC queue summary">
        <StatCard label="Pending review" icon="clock" tone="amber" value={formatNumber(stats.data?.pending)} hint="Awaiting a decision" />
        <StatCard label="Approved" icon="checkCircle" tone="green" value={formatNumber(stats.data?.approved)} hint="Verified customers" />
        <StatCard label="Rejected" icon="xCircle" tone="red" value={formatNumber(stats.data?.rejected)} hint="Turned down on review" />
        <StatCard label="All applications" icon="idCard" tone="blue" value={formatNumber(stats.data?.total)} hint="Every review cycle on record" />
      </div>

      <Card bodyless className="table-card">
        <div className="status-tabs status-tabs--card" role="tablist" aria-label="KYC application status">
          {TABS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={tab === item.value}
              onClick={() => setFilter("status", item.value)}
            >
              {item.label}
              {item.value !== "ALL" && stats.data ? (
                <span className="tab-count">
                  {item.value === "PENDING"
                    ? stats.data.pending
                    : item.value === "APPROVED"
                      ? stats.data.approved
                      : stats.data.rejected}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <TableHeader
          title={TABS.find((item) => item.value === tab)?.label ?? "Applications"}
          count={query.data?.total}
          description="Select a customer to open the full application."
        />

        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search applications"
            placeholder="Search by customer name or mobile"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          {auth.can(PERMISSIONS.merchantsView) ? (
            <Field label="Merchant" hideLabel>
              <Select
                value={values.merchant}
                onChange={(event) => setFilter("merchant", event.target.value)}
                placeholder={merchants.isLoading ? "Loading…" : "All merchants"}
                disabled={merchants.isLoading}
                options={(merchants.data?.items ?? []).map((merchant) => ({
                  value: merchant.id,
                  label: merchant.business_name
                }))}
              />
            </Field>
          ) : null}
        </FilterBar>

        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}

        <DataTable
          caption="Customer KYC applications"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(item) => item.id}
          getRowHref={(item) => `/admin/customers/${item.id}`}
          rowLabel={(item) => item.customer_name ?? item.id}
          rowActions={(item) => [
            { label: "Open application", icon: "eye", onSelect: () => navigate(`/admin/customers/${item.id}`) }
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState
                icon="search"
                title="No applications match your filters"
                description="Try a different name, merchant or status."
                action={
                  <Button variant="secondary" onClick={reset}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState icon="idCard" title={empty.title} description={empty.description} />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              itemLabel="applications"
              disabled={query.isFetching}
            />
          }
        />
      </Card>

      <p className="meta">
        Reviewing is done by the merchant that holds the customer relationship, so this screen is read-only. Statuses
        shown here are {statusMeta("PENDING").label.toLowerCase()}, {statusMeta("APPROVED").label.toLowerCase()} and{" "}
        {statusMeta("REJECTED").label.toLowerCase()}.
      </p>
    </div>
  );
}
