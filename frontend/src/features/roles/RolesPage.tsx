import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { queryKeys } from "../../api/query-keys";
import { listRoles, type Role } from "../../api/roles.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge, StatusBadge } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { CHANNELS, roleDescription } from "../../utils/labels";
import { RoleFormDialog } from "./RoleFormDialog";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "panel"] as const;

export function RolesPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const params = {
    search: values.search || undefined,
    is_active: values.status === "active" ? true : values.status === "inactive" ? false : undefined,
    login_channel: values.panel || undefined,
    page,
    page_size: PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.roles.list(params),
    queryFn: ({ signal }) => listRoles(params, signal),
    placeholderData: keepPreviousData
  });

  const columns: Column<Role>[] = [
    {
      key: "name",
      header: "Role",
      primary: true,
      render: (role) => (
        <div className="cell-primary__text">
          <Link to={`/admin/roles/${role.id}`} className="cell-primary__title">
            {role.name}
          </Link>
          <span className="cell-primary__subtitle">{roleDescription(role) ?? (role.is_system ? "Built-in role" : "No description")}</span>
        </div>
      )
    },
    {
      key: "type",
      header: "Type",
      render: (role) => (role.is_system ? <Badge tone="info">Built-in</Badge> : <Badge>Custom</Badge>)
    },
    {
      key: "status",
      header: "Status",
      render: (role) => <StatusBadge status={role.is_active ? "ACTIVE" : "INACTIVE"} />
    }
  ];

  return (
    <div className="page">
      <PageHeader
        title="Roles"
        description="Roles decide which panels people can use and what they can do there."
        breadcrumbs={[{ label: "Dashboard", to: "/admin/dashboard" }, { label: "Roles" }]}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          auth.can(PERMISSIONS.rolesCreate) ? (
            <Button variant="accent" icon="plus" onClick={() => setAdding(true)}>
              Add role
            </Button>
          ) : undefined
        }
      />
      <Card bodyless className="table-card">
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search roles"
            placeholder="Search by role name"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Status">
            <Select
              value={values.status}
              onChange={(event) => setFilter("status", event.target.value)}
              options={[
                { value: "active", label: "Active" },
                { value: "inactive", label: "Inactive" }
              ]}
              placeholder="All statuses"
            />
          </Field>
          <Field label="Can sign in to">
            <Select
              value={values.panel}
              onChange={(event) => setFilter("panel", event.target.value)}
              options={CHANNELS.map((channel) => ({ value: channel.code, label: channel.label }))}
              placeholder="Any panel"
            />
          </Field>
        </FilterBar>
        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}
        <DataTable
          caption="Roles"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(role) => role.id}
          getRowHref={(role) => `/admin/roles/${role.id}`}
          rowLabel={(role) => role.name}
          rowActions={(role) => [{ label: "View details", icon: "eye", onSelect: () => navigate(`/admin/roles/${role.id}`) }]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState icon="search" title="No roles match your filters" description="Try a different search or clear the filters." />
            ) : (
              <EmptyState icon="shield" title="No roles yet" description="Roles you add will appear here." />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              itemLabel="roles"
              disabled={query.isFetching}
            />
          }
        />
      </Card>
      {adding ? <RoleFormDialog onClose={() => setAdding(false)} /> : null}
    </div>
  );
}
