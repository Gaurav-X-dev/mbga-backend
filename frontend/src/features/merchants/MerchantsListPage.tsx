import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { listMerchants, type Merchant } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate } from "../../utils/format";
import { formatMobileNumber } from "../../utils/mobile";
import { useMerchantStatusActions } from "./useMerchantStatus";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "city", "state"] as const;
const STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "BLOCKED", label: "Blocked" }
];

export function MerchantsListPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const [cityText, setCityText] = useSearchFilter(values.city, (value) => setFilter("city", value));
  const [stateText, setStateText] = useSearchFilter(values.state, (value) => setFilter("state", value));
  const status = useMerchantStatusActions();

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

  const columns: Column<Merchant>[] = [
    {
      key: "business",
      header: "Merchant",
      primary: true,
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
      header: "Contact",
      render: (merchant) => (
        <div className="cell-primary__text">
          <span>{merchant.contact_person_name ?? "—"}</span>
          <span className="cell-primary__subtitle nowrap">{formatMobileNumber(merchant.mobile_number) || "—"}</span>
        </div>
      )
    },
    {
      key: "location",
      header: "Location",
      render: (merchant) => [merchant.city, merchant.state].filter(Boolean).join(", ") || "—"
    },
    { key: "status", header: "Status", render: (merchant) => <StatusBadge status={merchant.status} /> },
    {
      key: "created",
      header: "Added on",
      mobileLabel: "Added on",
      render: (merchant) => <span className="nowrap">{formatDate(merchant.created_at)}</span>
    }
  ];

  const total = query.data?.total ?? 0;

  return (
    <div className="page">
      <PageHeader
        title="Merchants"
        description="Businesses that distribute LPG through MBGA."
        breadcrumbs={[{ label: "Dashboard", to: "/admin/dashboard" }, { label: "Merchants" }]}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          auth.can(PERMISSIONS.merchantsCreate) ? (
            <ButtonLink to="/admin/merchants/new" variant="accent" icon="plus">
              Add merchant
            </ButtonLink>
          ) : undefined
        }
      />

      <Card bodyless className="table-card">
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search merchants"
            placeholder="Search by name, code or mobile"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Status">
            <Select
              value={values.status}
              onChange={(event) => setFilter("status", event.target.value)}
              options={STATUS_OPTIONS}
              placeholder="All statuses"
            />
          </Field>
          <Field label="City">
            <Input value={cityText} onChange={(event) => setCityText(event.target.value)} placeholder="Any city" />
          </Field>
          <Field label="State">
            <Input value={stateText} onChange={(event) => setStateText(event.target.value)} placeholder="Any state" />
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
                title="No merchants match your filters"
                description="Try a different search or clear the filters."
              />
            ) : (
              <EmptyState
                icon="store"
                title="No merchants yet"
                description="Add your first merchant to start managing their business on MBGA."
                action={
                  auth.can(PERMISSIONS.merchantsCreate) ? (
                    <ButtonLink to="/admin/merchants/new" variant="accent" icon="plus">
                      Add merchant
                    </ButtonLink>
                  ) : undefined
                }
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
