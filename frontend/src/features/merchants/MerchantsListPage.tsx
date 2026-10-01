import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { listMerchants, type Merchant } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button, ButtonLink } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, MiniStat, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { downloadCsv } from "../../utils/csv";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatNumber } from "../../utils/format";
import { statusMeta } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { useMerchantStatusActions } from "./useMerchantStatus";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "city", "state"] as const;
const STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "BLOCKED", label: "Blocked" }
];

/** Totals for the strip above the table. Failures stay quiet: the table reports its own errors. */
function useStatusTotal(status: "" | "ACTIVE" | "BLOCKED") {
  const params = { status: status || undefined, limit: 1, offset: 0 };
  return useQuery({
    queryKey: queryKeys.merchants.list(params),
    queryFn: ({ signal }) => listMerchants(params, signal),
    select: (data) => data.total,
    staleTime: 60_000,
    retry: false
  });
}

export function MerchantsListPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const [cityText, setCityText] = useSearchFilter(values.city, (value) => setFilter("city", value));
  const [stateText, setStateText] = useSearchFilter(values.state, (value) => setFilter("state", value));
  const status = useMerchantStatusActions();
  const canCreate = auth.can(PERMISSIONS.merchantsCreate);

  const params = {
    search: values.search || undefined,
    status: values.status || undefined,
    city: values.city || undefined,
    state: values.state || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.merchants.list(params),
    queryFn: ({ signal }) => listMerchants(params, signal),
    placeholderData: keepPreviousData
  });
  const allTotal = useStatusTotal("");
  const activeTotal = useStatusTotal("ACTIVE");
  const blockedTotal = useStatusTotal("BLOCKED");

  const columns: Column<Merchant>[] = [
    {
      key: "business",
      header: "Merchant",
      primary: true,
      sortValue: (merchant) => merchant.business_name,
      render: (merchant) => (
        <div className="cell-primary">
          <UserAvatar name={merchant.business_name} />
          <div className="cell-primary__text">
            <Link to={`/admin/merchants/${merchant.id}`} className="cell-primary__title">
              {merchant.business_name}
            </Link>
            <span className="cell-primary__subtitle">Code {merchant.merchant_code}</span>
          </div>
        </div>
      )
    },
    {
      key: "contact",
      header: "Owner / Contact",
      sortValue: (merchant) => merchant.contact_person_name,
      render: (merchant) => (
        <div className="cell-stack">
          <span>{merchant.contact_person_name ?? "—"}</span>
          <small className="nowrap">{formatMobileNumber(merchant.mobile_number) || "—"}</small>
        </div>
      )
    },
    {
      key: "location",
      header: "City",
      sortValue: (merchant) => merchant.city,
      render: (merchant) =>
        merchant.city || merchant.state ? (
          <div className="cell-stack">
            <span>{merchant.city ?? "—"}</span>
            {merchant.state ? <small>{merchant.state}</small> : null}
          </div>
        ) : (
          <span className="cell-muted">Not set</span>
        )
    },
    {
      key: "gst",
      header: "GSTIN",
      hideOnMobile: true,
      render: (merchant) => (merchant.gst_number ? <span className="mono">{merchant.gst_number}</span> : <span className="cell-muted">—</span>)
    },
    {
      key: "status",
      header: "Status",
      sortValue: (merchant) => merchant.status,
      render: (merchant) => <StatusBadge status={merchant.status} />
    },
    {
      key: "created",
      header: "Created On",
      mobileLabel: "Created on",
      sortValue: (merchant) => merchant.created_at,
      render: (merchant) => <span className="nowrap">{formatDate(merchant.created_at)}</span>
    }
  ];

  const total = query.data?.total ?? 0;

  function exportRows() {
    const rows = query.data?.items ?? [];
    downloadCsv(
      "mbga-merchants.csv",
      ["Merchant", "Code", "Contact person", "Mobile", "Email", "City", "State", "GSTIN", "Status", "Created on"],
      rows.map((merchant) => [
        merchant.business_name,
        merchant.merchant_code,
        merchant.contact_person_name,
        merchant.mobile_number,
        merchant.email,
        merchant.city,
        merchant.state,
        merchant.gst_number,
        statusMeta(merchant.status).label,
        formatDate(merchant.created_at)
      ])
    );
  }

  const addButton = canCreate ? (
    <ButtonLink to="/admin/merchants/new" variant="primary" icon="plus">
      Add Merchant
    </ButtonLink>
  ) : undefined;

  return (
    <div className="page list-page">
      <PageHeader
        title="Merchant Network"
        documentTitle="Merchant Network"
        description="Manage gas agency partners, operating status, and access."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={addButton}
      />

      <div className="mini-stat-strip" aria-label="Merchant totals">
        <MiniStat label="Total merchants" value={formatNumber(allTotal.data)} icon="store" tone="blue" />
        <MiniStat label="Active" value={formatNumber(activeTotal.data)} icon="checkCircle" tone="green" />
        <MiniStat label="Blocked" value={formatNumber(blockedTotal.data)} icon="ban" tone="red" />
        <MiniStat
          label="Active coverage"
          value={allTotal.data ? `${Math.round(((activeTotal.data ?? 0) / allTotal.data) * 100)}%` : "—"}
          icon="mapPin"
          tone="orange"
        />
      </div>

      <Card bodyless className="table-card">
        <TableHeader
          title="All merchants"
          count={query.data ? total : undefined}
          description="Click a merchant to view details, staff and access."
        />
        <FilterBar
          onReset={reset}
          canReset={hasFilters}
          actions={
            <Button variant="secondary" size="sm" icon="download" onClick={exportRows} disabled={!query.data?.items.length}>
              Export
            </Button>
          }
        >
          <SearchInput
            label="Search merchants"
            placeholder="Search by name, code or mobile"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Status" hideLabel>
            <Select
              value={values.status}
              onChange={(event) => setFilter("status", event.target.value)}
              options={STATUS_OPTIONS}
              placeholder="All statuses"
            />
          </Field>
          <Field label="City" hideLabel>
            <Input value={cityText} onChange={(event) => setCityText(event.target.value)} placeholder="Any city" />
          </Field>
          <Field label="State" hideLabel>
            <Input value={stateText} onChange={(event) => setStateText(event.target.value)} placeholder="Any state / region" />
          </Field>
        </FilterBar>

        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}

        <DataTable
          caption="Merchants"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(merchant) => merchant.id}
          getRowHref={(merchant) => `/admin/merchants/${merchant.id}`}
          rowLabel={(merchant) => merchant.business_name}
          rowActions={(merchant) => [
            { label: "View details", icon: "eye", onSelect: () => navigate(`/admin/merchants/${merchant.id}`) },
            ...status.actionsFor(merchant)
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState
                icon="search"
                title="No merchants found"
                description="Try adjusting filters or add a new merchant."
                action={
                  <Button variant="secondary" onClick={reset}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon="store"
                title="No merchants yet"
                description="Add your first gas agency partner to start managing operations on MBGA."
                action={addButton}
              />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              onPageChange={setPage}
              itemLabel="merchants"
              disabled={query.isFetching}
            />
          }
        />
      </Card>
      {status.dialog}
    </div>
  );
}
