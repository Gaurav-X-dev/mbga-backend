import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getAdminDashboardSummary } from "../../api/dashboard.api";
import { queryKeys } from "../../api/query-keys";
import { listUsers, type User } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, MiniStat, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { downloadCsv } from "../../utils/csv";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatNumber } from "../../utils/format";
import { roleLabel, statusMeta } from "../../utils/labels";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const canCreate = auth.can(PERMISSIONS.usersCreate);
  const [adding, setAdding] = useState(() => canCreate && searchParams.get("create") === "1");
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
  // Header figures; failures stay quiet because the table reports its own errors.
  const summary = useQuery({
    queryKey: queryKeys.adminDashboard.summary(),
    queryFn: ({ signal }) => getAdminDashboardSummary(signal),
    enabled: auth.can(PERMISSIONS.dashboardView),
    staleTime: 60_000,
    retry: false
  });
  const pendingParams = { status: "PENDING", limit: 1, offset: 0 };
  const pending = useQuery({
    queryKey: queryKeys.users.list(pendingParams),
    queryFn: ({ signal }) => listUsers(pendingParams, signal),
    select: (data) => data.total,
    staleTime: 60_000,
    retry: false
  });

  function closeAdd() {
    setAdding(false);
    if (searchParams.has("create")) {
      const next = new URLSearchParams(searchParams);
      next.delete("create");
      setSearchParams(next, { replace: true });
    }
  }

  const columns: Column<User>[] = [
    {
      key: "name",
      header: "User",
      primary: true,
      sortValue: (user) => userDisplayName(user),
      render: (user) => (
        <div className="cell-primary">
          <UserAvatar name={userDisplayName(user)} />
          <div className="cell-primary__text">
            <Link to={`/admin/users/${user.id}`} className="cell-primary__title">
              {userDisplayName(user)}
            </Link>
            <span className="cell-primary__subtitle">{user.username ? `@${user.username}` : "No username"}</span>
          </div>
        </div>
      )
    },
    {
      key: "contact",
      header: "Mobile / Email",
      render: (user) => (
        <div className="cell-stack">
          <span className="nowrap">{formatMobileNumber(user.mobile_number) || "—"}</span>
          <small>{user.email ?? "No email"}</small>
        </div>
      )
    },
    {
      key: "type",
      header: "Role",
      sortValue: (user) => roleLabel(user.role),
      render: (user) => <Badge tone={user.role === "super_admin" ? "accent" : "neutral"}>{roleLabel(user.role)}</Badge>
    },
    { key: "status", header: "Status", sortValue: (user) => user.status, render: (user) => <StatusBadge status={user.status} /> },
    {
      key: "created",
      header: "Added On",
      sortValue: (user) => user.created_at,
      render: (user) => <span className="nowrap">{formatDate(user.created_at)}</span>
    }
  ];

  return (
    <div className="page list-page">
      <PageHeader
        title="Team Users"
        documentTitle="Team Users"
        description="Manage admin, merchant, delivery, and support users."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          canCreate ? (
            <Button variant="primary" icon="userPlus" onClick={() => setAdding(true)}>
              Add user
            </Button>
          ) : undefined
        }
      />

      <div className="mini-stat-strip" aria-label="User totals">
        <MiniStat label="Total users" value={formatNumber(summary.data?.users)} icon="users" tone="blue" />
        <MiniStat label="Active users" value={formatNumber(summary.data?.active_users)} icon="userCheck" tone="green" />
        <MiniStat label="Blocked users" value={formatNumber(summary.data?.blocked_users)} icon="lock" tone="red" />
        <MiniStat label="Pending invites" value={formatNumber(pending.data)} icon="mail" tone="amber" />
      </div>

      <Card bodyless className="table-card">
        <TableHeader
          title="All team users"
          count={query.data?.total}
          description="Roles decide what each person can do; channels decide where they can sign in."
        />
        <FilterBar
          onReset={reset}
          canReset={hasFilters}
          actions={
            <Button
              variant="secondary"
              size="sm"
              icon="download"
              disabled={!query.data?.items.length}
              onClick={() =>
                downloadCsv(
                  "mbga-team-users.csv",
                  ["Name", "Username", "Mobile", "Email", "Role", "Status", "Added on"],
                  (query.data?.items ?? []).map((user) => [
                    userDisplayName(user),
                    user.username,
                    user.mobile_number,
                    user.email,
                    roleLabel(user.role),
                    statusMeta(user.status).label,
                    formatDate(user.created_at)
                  ])
                )
              }
            >
              Export
            </Button>
          }
        >
          <SearchInput
            label="Search users"
            placeholder="Search by name, email, username or mobile"
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
            {
              label: "Assign role",
              icon: "shield",
              onSelect: () => navigate(`/admin/users/${user.id}`),
              hidden: !auth.can(PERMISSIONS.usersAssignRoles)
            },
            ...actions.actionsFor(user)
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState
                icon="search"
                title="No users match your filters"
                description="Try a different search or clear the filters."
                action={
                  <Button variant="secondary" onClick={reset}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon="users"
                title="No users yet"
                description="Invite your first team member to start delegating work."
                action={
                  canCreate ? (
                    <Button variant="primary" icon="userPlus" onClick={() => setAdding(true)}>
                      Add user
                    </Button>
                  ) : undefined
                }
              />
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
      <AddUserDialog open={adding} onClose={closeAdd} />
      {actions.dialog}
    </div>
  );
}
