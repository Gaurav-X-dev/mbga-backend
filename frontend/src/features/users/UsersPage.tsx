import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { queryKeys } from "../../api/query-keys";
import { listUsers, type User } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate } from "../../utils/format";
import { roleLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { AddUserDialog } from "./AddUserDialog";
import { useUserStatusActions } from "./useUserActions";
import { userDisplayName } from "./user-utils";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status"] as const;
const STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "INACTIVE", label: "Inactive" },
  { value: "PENDING", label: "Pending" },
  { value: "BLOCKED", label: "Blocked" }
];

export function UsersPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const actions = useUserStatusActions();

  const params = {
    search: values.search || undefined,
    status: values.status || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.users.list(params),
    queryFn: ({ signal }) => listUsers(params, signal),
    placeholderData: keepPreviousData
  });

  const columns: Column<User>[] = [
    {
      key: "name",
      header: "User",
      primary: true,
      render: (user) => (
        <div className="cell-primary">
          <UserAvatar name={userDisplayName(user)} />
          <div className="cell-primary__text">
            <Link to={`/admin/users/${user.id}`} className="cell-primary__title">
              {userDisplayName(user)}
            </Link>
            <span className="cell-primary__subtitle">{user.email ?? "No email"}</span>
          </div>
        </div>
      )
    },
    {
      key: "mobile",
      header: "Mobile number",
      render: (user) => <span className="nowrap">{formatMobileNumber(user.mobile_number) || "—"}</span>
    },
    { key: "type", header: "Account type", render: (user) => roleLabel(user.role) },
    { key: "status", header: "Status", render: (user) => <StatusBadge status={user.status} /> },
    { key: "created", header: "Added on", render: (user) => <span className="nowrap">{formatDate(user.created_at)}</span> }
  ];

  return (
    <div className="page">
      <PageHeader
        title="Users"
        description="Everyone who can sign in to MBGA panels and apps."
        breadcrumbs={[{ label: "Dashboard", to: "/admin/dashboard" }, { label: "Users" }]}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          auth.can(PERMISSIONS.usersCreate) ? (
            <Button variant="accent" icon="plus" onClick={() => setAdding(true)}>
              Add user
            </Button>
          ) : undefined
        }
      />
      <Card bodyless className="table-card">
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search users"
            placeholder="Search by email, username or mobile"
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
        </FilterBar>
        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}
        <DataTable
          caption="Users"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(user) => user.id}
          getRowHref={(user) => `/admin/users/${user.id}`}
          rowLabel={userDisplayName}
          rowActions={(user) => [
            { label: "View details", icon: "eye", onSelect: () => navigate(`/admin/users/${user.id}`) },
            ...actions.actionsFor(user)
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState icon="search" title="No users match your filters" description="Try a different search or clear the filters." />
            ) : (
              <EmptyState icon="users" title="No users yet" description="Users you add will appear here." />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              itemLabel="users"
              disabled={query.isFetching}
            />
          }
        />
      </Card>
      <p className="meta">Search matches email address, username and mobile number. Names are not searchable yet.</p>
      <AddUserDialog open={adding} onClose={() => setAdding(false)} />
      {actions.dialog}
    </div>
  );
}
