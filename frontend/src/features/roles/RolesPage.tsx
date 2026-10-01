import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getAdminDashboardSummary } from "../../api/dashboard.api";
import { queryKeys } from "../../api/query-keys";
import { listRoleChannels, listRolePermissions, listRoleUsers, listRoles, type Role } from "../../api/roles.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { DetailDrawer, DrawerSection } from "../../components/feedback/Dialogs";
import { EmptyState, InlineError, RefreshIndicator, Skeleton } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatNumber } from "../../utils/format";
import { CHANNELS, channelLabel, permissionModuleLabel, permissionModuleOrder, roleDescription } from "../../utils/labels";
import { userDisplayName } from "../users/user-utils";
import { RoleFormDialog } from "./RoleFormDialog";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "panel"] as const;
const DETAIL_STALE = 5 * 60_000;

function useRoleChannels(roleId: string) {
  return useQuery({
    queryKey: queryKeys.roles.channels(roleId),
    queryFn: ({ signal }) => listRoleChannels(roleId, signal),
    staleTime: DETAIL_STALE,
    retry: false
  });
}

function useRolePermissions(roleId: string) {
  return useQuery({
    queryKey: queryKeys.roles.permissions(roleId),
    queryFn: ({ signal }) => listRolePermissions(roleId, signal),
    staleTime: DETAIL_STALE,
    retry: false
  });
}

const SHORT_CHANNEL: Record<string, string> = { ADMIN: "Admin", MERCHANT: "Merchant", DELIVERY: "Delivery", CUSTOMER: "Customer" };

function ChannelsCell({ roleId }: { roleId: string }) {
  const query = useRoleChannels(roleId);
  if (query.isLoading) return <Skeleton width={90} height={12} />;
  const allowed = (query.data ?? []).filter((item) => item.is_allowed);
  if (query.error) return <span className="cell-muted">—</span>;
  if (allowed.length === 0) return <span className="cell-muted">No channels</span>;
  return (
    <span className="tag-list">
      {allowed.map((item) => (
        <Badge key={item.login_channel} tone="info">
          {SHORT_CHANNEL[item.login_channel] ?? channelLabel(item.login_channel)}
        </Badge>
      ))}
    </span>
  );
}

function PermissionCountCell({ roleId }: { roleId: string }) {
  const query = useRolePermissions(roleId);
  if (query.isLoading) return <Skeleton width={28} height={12} />;
  if (query.error) return <span className="cell-muted">—</span>;
  return <strong>{formatNumber(query.data?.length ?? 0)}</strong>;
}

function RoleDrawer({ role, onClose }: { role: Role; onClose: () => void }) {
  const auth = useAuth();
  const channels = useRoleChannels(role.id);
  const permissions = useRolePermissions(role.id);
  const users = useQuery({
    queryKey: queryKeys.roles.users(role.id),
    queryFn: ({ signal }) => listRoleUsers(role.id, signal),
    enabled: auth.can(PERMISSIONS.usersView),
    staleTime: DETAIL_STALE
  });

  const grouped = Object.entries(
    (permissions.data ?? []).reduce<Record<string, string[]>>((acc, item) => {
      (acc[item.module] ??= []).push(item.name);
      return acc;
    }, {})
  ).sort(([a], [b]) => permissionModuleOrder(a) - permissionModuleOrder(b));

  return (
    <DetailDrawer
      open
      size="lg"
      onClose={onClose}
      title={role.name}
      subtitle={roleDescription(role) ?? (role.is_system ? "Built-in MBGA role" : "Custom role")}
      meta={
        <>
          <StatusBadge status={role.is_active ? "ACTIVE" : "INACTIVE"} />
          {role.is_system ? <Badge tone="info">Built-in</Badge> : <Badge>Custom</Badge>}
        </>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <ButtonLink to={`/admin/roles/${role.id}`} variant="primary" icon="edit">
            {auth.can(PERMISSIONS.rolesUpdate) ? "Edit role" : "Open role"}
          </ButtonLink>
        </>
      }
    >
      <DrawerSection title="Role information">
        <DetailsPanel
          items={[
            { label: "Role code", value: <span className="mono">{role.code}</span> },
            { label: "Type", value: role.is_system ? "Built-in role" : "Custom role" },
            { label: "Permissions", value: permissions.data ? formatNumber(permissions.data.length) : "—" },
            { label: "Users assigned", value: users.data ? formatNumber(users.data.length) : "—" }
          ]}
        />
      </DrawerSection>

      <DrawerSection title="Login channels">
        <p className="text-small text-muted">Assign login channels carefully to prevent unauthorized access.</p>
        {channels.isLoading ? (
          <Skeleton height={30} />
        ) : (
          <div className="channel-chips">
            {CHANNELS.map((channel) => {
              const on = channels.data?.some((item) => item.login_channel === channel.code && item.is_allowed);
              return (
                <span key={channel.code} className={`channel-chip ${on ? "is-on" : "is-off"}`}>
                  <Icon name={on ? "checkCircle" : "ban"} size={14} />
                  {channel.label}
                </span>
              );
            })}
          </div>
        )}
      </DrawerSection>

      <DrawerSection title="Assigned permissions">
        <p className="text-small text-muted">Permissions are grouped by module.</p>
        {permissions.isLoading ? (
          <Skeleton height={80} />
        ) : grouped.length === 0 ? (
          <p className="text-small text-muted">This role has no permissions yet.</p>
        ) : (
          <ul className="health-list list-plain">
            {grouped.map(([module, names]) => (
              <li key={module} title={names.join(", ")}>
                <span>{permissionModuleLabel(module)}</span>
                <strong>{formatNumber(names.length)}</strong>
              </li>
            ))}
          </ul>
        )}
      </DrawerSection>

      {auth.can(PERMISSIONS.usersView) ? (
        <DrawerSection title="Assigned users">
          {users.isLoading ? (
            <Skeleton height={60} />
          ) : users.data && users.data.length > 0 ? (
            <ul className="activity-list list-plain">
              {users.data.slice(0, 6).map((user) => (
                <li key={user.id} className="activity-item">
                  <UserAvatar name={userDisplayName(user)} />
                  <div className="activity-item__body">
                    <span className="activity-item__title">
                      <Link to={`/admin/users/${user.id}`}>{userDisplayName(user)}</Link>
                      <StatusBadge status={user.status} />
                    </span>
                    <span className="activity-item__time">{user.email ?? "No email"}</span>
                  </div>
                </li>
              ))}
              {users.data.length > 6 ? (
                <li className="meta">and {formatNumber(users.data.length - 6)} more on the role page</li>
              ) : null}
            </ul>
          ) : (
            <p className="text-small text-muted">No one has this role yet.</p>
          )}
        </DrawerSection>
      ) : null}
    </DetailDrawer>
  );
}

export function RolesPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canCreate = auth.can(PERMISSIONS.rolesCreate);
  const [adding, setAdding] = useState(() => canCreate && searchParams.get("create") === "1");
  const [openRole, setOpenRole] = useState<Role | null>(null);
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
  const summary = useQuery({
    queryKey: queryKeys.adminDashboard.summary(),
    queryFn: ({ signal }) => getAdminDashboardSummary(signal),
    enabled: auth.can(PERMISSIONS.dashboardView),
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

  const columns: Column<Role>[] = [
    {
      key: "name",
      header: "Role Name",
      primary: true,
      sortValue: (role) => role.name,
      render: (role) => (
        <div className="cell-primary">
          <span className={`stat-card__icon ${role.is_system ? "tone-blue" : "tone-orange"}`} style={{ width: 32, height: 32, borderRadius: 8 }} aria-hidden="true">
            <Icon name="shield" size={15} />
          </span>
          <div className="cell-primary__text">
            <Link to={`/admin/roles/${role.id}`} className="cell-primary__title">
              {role.name}
            </Link>
            <span className="cell-primary__subtitle">{roleDescription(role) ?? (role.is_system ? "Built-in role" : "No description")}</span>
          </div>
        </div>
      )
    },
    {
      key: "type",
      header: "Type",
      sortValue: (role) => (role.is_system ? 0 : 1),
      render: (role) => (role.is_system ? <Badge tone="info">Built-in</Badge> : <Badge>Custom</Badge>)
    },
    { key: "channels", header: "Channels", render: (role) => <ChannelsCell roleId={role.id} /> },
    { key: "permissions", header: "Permissions", align: "center", render: (role) => <PermissionCountCell roleId={role.id} /> },
    {
      key: "status",
      header: "Status",
      sortValue: (role) => (role.is_active ? 0 : 1),
      render: (role) => <StatusBadge status={role.is_active ? "ACTIVE" : "INACTIVE"} />
    }
  ];

  return (
    <div className="page list-page">
      <PageHeader
        title="Roles & Access"
        documentTitle="Roles & Access"
        description="Control which modules this role can access and which login channels it may use."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            {auth.can(PERMISSIONS.permissionsView) ? (
              <ButtonLink to="/admin/permissions" variant="secondary" icon="key">
                Permission matrix
              </ButtonLink>
            ) : null}
            {canCreate ? (
              <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>
                Add role
              </Button>
            ) : null}
          </>
        }
      />

      <div className="stat-grid" aria-label="Role summary">
        <StatCard label="Total roles" icon="shield" tone="blue" value={formatNumber(summary.data?.roles)} hint="Built-in and custom" />
        <StatCard label="Active roles" icon="checkCircle" tone="green" value={formatNumber(summary.data?.active_roles)} hint="Can be assigned to users" />
        <StatCard
          label="Inactive roles"
          icon="ban"
          tone="slate"
          value={summary.data ? formatNumber(summary.data.roles - summary.data.active_roles) : "—"}
          hint="Kept for history, grant nothing"
        />
        <StatCard
          label="Permissions in catalogue"
          icon="key"
          tone="orange"
          value={formatNumber(summary.data?.active_permissions)}
          hint="Grouped by module"
          to={auth.can(PERMISSIONS.permissionsView) ? "/admin/permissions" : undefined}
          linkLabel="Open matrix"
        />
      </div>

      <Card bodyless className="table-card">
        <TableHeader title="All roles" count={query.data?.total} description="Select a role to see its channels, permissions and people." />
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search roles"
            placeholder="Search by role name"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Status" hideLabel>
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
          <Field label="Can sign in to" hideLabel>
            <Select
              value={values.panel}
              onChange={(event) => setFilter("panel", event.target.value)}
              options={CHANNELS.map((channel) => ({ value: channel.code, label: channel.label }))}
              placeholder="Any channel"
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
          onRowClick={(role) => setOpenRole(role)}
          isSelected={(role) => role.id === openRole?.id}
          rowLabel={(role) => role.name}
          rowActions={(role) => [
            { label: "Quick view", icon: "eye", onSelect: () => setOpenRole(role) },
            { label: "Open role", icon: "edit", onSelect: () => navigate(`/admin/roles/${role.id}`) }
          ]}
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
      {adding ? <RoleFormDialog onClose={closeAdd} /> : null}
      {openRole ? <RoleDrawer role={openRole} onClose={() => setOpenRole(null)} /> : null}
    </div>
  );
}
