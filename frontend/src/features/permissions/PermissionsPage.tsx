import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";

import { listPermissionsGrouped, type Permission } from "../../api/permissions.api";
import { queryKeys } from "../../api/query-keys";
import { listRolePermissions, listRoles, replaceRolePermissions, type Role } from "../../api/roles.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Icon, type IconName } from "../../components/common/Icon";
import { Badge } from "../../components/common/StatusBadge";
import { EmptyState, ErrorState, InlineError, LoadingSkeleton, Skeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { UnsavedChangesGuard } from "../../components/forms/FormParts";
import { Card, MiniStat, PageHeader } from "../../components/layout/Page";
import { FilterBar } from "../../components/tables/DataTable";
import { formatNumber, pluralize } from "../../utils/format";
import { PERMISSION_MODULES, permissionDescription, permissionModuleLabel, permissionModuleOrder } from "../../utils/labels";

const SUPER_ADMIN = "super_admin";

const MODULE_ICONS: Record<string, IconName> = {
  dashboard: "dashboard",
  merchants: "store",
  merchant_users: "users",
  customers: "idCard",
  customer_documents: "fileText",
  users: "users",
  roles: "shield",
  permissions: "key",
  authentication: "lock",
  delivery_users: "truck",
  drivers: "truck",
  trips: "truck",
  deliveries: "truck",
  orders: "cart",
  inventory: "box",
  cylinder_exchange: "refresh",
  pending_pickups: "clock",
  pricing: "wallet",
  payments: "wallet",
  reconciliation: "checkCircle",
  ledgers: "wallet",
  expenses: "wallet",
  reports: "chart",
  notifications: "bell",
  audit_logs: "history"
};

/** roleId -> permissionId -> desired state, only for cells that differ from what is saved. */
type Changes = Record<string, Record<string, boolean>>;

function countChanges(changes: Changes) {
  return Object.values(changes).reduce((sum, cells) => sum + Object.keys(cells).length, 0);
}

export function PermissionsPage() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const canSeeRoles = auth.can(PERMISSIONS.rolesView);
  const canEdit = canSeeRoles && auth.can(PERMISSIONS.rolesAssignPermissions);

  const [search, setSearch] = useState("");
  const [module, setModule] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [changes, setChanges] = useState<Changes>({});

  const catalogue = useQuery({
    queryKey: queryKeys.permissions.grouped(),
    queryFn: ({ signal }) => listPermissionsGrouped(signal),
    staleTime: 10 * 60_000
  });
  const rolesParams = { page: 1, page_size: 100 };
  const roles = useQuery({
    queryKey: queryKeys.roles.list(rolesParams),
    queryFn: ({ signal }) => listRoles(rolesParams, signal),
    enabled: canSeeRoles,
    staleTime: 5 * 60_000,
    retry: false
  });
  const roleList: Role[] = useMemo(
    () => [...(roles.data?.items ?? [])].sort((a, b) => Number(b.is_system) - Number(a.is_system) || a.name.localeCompare(b.name)),
    [roles.data]
  );
  const grants = useQueries({
    queries: roleList.map((role) => ({
      queryKey: queryKeys.roles.permissions(role.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => listRolePermissions(role.id, signal),
      staleTime: 5 * 60_000,
      retry: false
    }))
  });
  // What each role has saved on the server; undefined while that role is loading or failed.
  const saved: Record<string, Set<string> | undefined> = {};
  roleList.forEach((role, index) => {
    const data = grants[index]?.data;
    saved[role.id] = data ? new Set(data.map((item) => item.id)) : undefined;
  });

  const groups = [...(catalogue.data?.groups ?? [])].sort((a, b) => permissionModuleOrder(a.module) - permissionModuleOrder(b.module));
  const term = search.trim().toLowerCase();
  const visible = groups
    .filter((group) => !module || group.module === module)
    .map((group) => ({
      ...group,
      permissions: group.permissions.filter(
        (item) =>
          !term ||
          item.name.toLowerCase().includes(term) ||
          item.code.toLowerCase().includes(term) ||
          (item.description ?? "").toLowerCase().includes(term) ||
          permissionModuleLabel(group.module).toLowerCase().includes(term)
      )
    }))
    .filter((group) => group.permissions.length > 0);
  const visibleCount = visible.reduce((count, group) => count + group.permissions.length, 0);
  const shownRoles = roleFilter ? roleList.filter((role) => role.id === roleFilter) : roleList;
  const pending = countChanges(changes);
  const hasFilters = Boolean(search || module || roleFilter);

  const isLocked = (role: Role) => !canEdit || role.code === SUPER_ADMIN || !saved[role.id];

  function isGranted(role: Role, permissionId: string) {
    // The backend grants Super Admin everything regardless of its stored assignments.
    if (role.code === SUPER_ADMIN) return true;
    const change = changes[role.id]?.[permissionId];
    if (change !== undefined) return change;
    return saved[role.id]?.has(permissionId) ?? false;
  }

  function setCells(role: Role, permissionIds: string[], on: boolean) {
    setChanges((previous) => {
      const cells = { ...(previous[role.id] ?? {}) };
      permissionIds.forEach((id) => {
        const original = saved[role.id]?.has(id) ?? false;
        if (original === on) delete cells[id];
        else cells[id] = on;
      });
      const next = { ...previous, [role.id]: cells };
      if (Object.keys(cells).length === 0) delete next[role.id];
      return next;
    });
  }

  const mutation = useMutation({
    mutationFn: async () => {
      for (const [roleId, cells] of Object.entries(changes)) {
        const next = new Set(saved[roleId]);
        Object.entries(cells).forEach(([permissionId, on]) => (on ? next.add(permissionId) : next.delete(permissionId)));
        await replaceRolePermissions(roleId, [...next]);
      }
    },
    onSuccess: () => {
      const count = Object.keys(changes).length;
      Object.keys(changes).forEach((roleId) => void queryClient.invalidateQueries({ queryKey: queryKeys.roles.permissions(roleId) }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      setChanges({});
      toast.success(`Permissions saved for ${pluralize(count, "role")}. Changes apply the next time affected users sign in or refresh.`);
    }
  });

  function clearFilters() {
    setSearch("");
    setModule("");
    setRoleFilter("");
  }

  return (
    <div className="page permissions-page">
      <UnsavedChangesGuard when={pending > 0 && !mutation.isPending} />
      <PageHeader
        title="Permission Matrix"
        documentTitle="Permission Matrix"
        description="Control which modules each role can access. Permissions are grouped by module."
        meta={catalogue.data ? <span className="sr-only">{formatNumber(catalogue.data.total)} permissions available</span> : undefined}
        actions={
          canEdit ? (
            <>
              <Button variant="secondary" onClick={() => setChanges({})} disabled={pending === 0 || mutation.isPending}>
                Discard
              </Button>
              <Button
                variant="primary"
                icon="check"
                onClick={() => mutation.mutate()}
                disabled={pending === 0}
                loading={mutation.isPending}
                loadingText="Saving…"
              >
                Save changes
              </Button>
            </>
          ) : (
            <Badge tone="info">Read only</Badge>
          )
        }
      />

      {catalogue.data ? (
        <div className="mini-stat-strip" aria-label="Permission catalogue summary">
          <MiniStat label="Active permissions" value={formatNumber(catalogue.data.total)} icon="key" tone="blue" />
          <MiniStat label="Modules" value={formatNumber(groups.length)} icon="dashboard" tone="slate" />
          <MiniStat label="Roles in matrix" value={canSeeRoles ? formatNumber(roleList.length) : "—"} icon="shield" tone="green" />
          <MiniStat label="Unsaved changes" value={formatNumber(pending)} icon="edit" tone={pending ? "orange" : "slate"} />
        </div>
      ) : null}

      {mutation.error ? <InlineError error={mutation.error} title="Some changes could not be saved" /> : null}
      {roles.error ? <InlineError error={roles.error} title="Roles could not be loaded; showing the catalogue only" onRetry={() => void roles.refetch()} /> : null}

      <Card bodyless className="table-card">
        <FilterBar onReset={clearFilters} canReset={hasFilters}>
          <SearchInput
            label="Search permissions"
            placeholder="Search by permission or module…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Field label="Module" hideLabel>
            <Select
              value={module}
              onChange={(event) => setModule(event.target.value)}
              placeholder="All modules"
              options={groups.map((group) => ({ value: group.module, label: permissionModuleLabel(group.module) }))}
            />
          </Field>
          {canSeeRoles ? (
            <Field label="Role" hideLabel>
              <Select
                value={roleFilter}
                onChange={(event) => setRoleFilter(event.target.value)}
                placeholder="All roles"
                options={roleList.map((role) => ({ value: role.id, label: role.name }))}
              />
            </Field>
          ) : null}
        </FilterBar>

        {catalogue.data && visible.length > 0 ? (
          <p className="meta" style={{ padding: "var(--space-3) var(--space-5) 0" }} aria-live="polite">
            Showing {formatNumber(visibleCount)} of {formatNumber(catalogue.data.total)} permissions
            {canEdit ? " · Click a cell to grant or revoke. The Super Admin role always has full access." : ""}
          </p>
        ) : null}

        {catalogue.isLoading ? (
          <LoadingSkeleton rows={6} label="Loading permissions" />
        ) : catalogue.error ? (
          <ErrorState error={catalogue.error} onRetry={() => void catalogue.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={term || module ? "search" : "key"}
            title={term || module ? "No permissions match your filters" : "No permissions available"}
            description={term || module ? "Try a different keyword or clear the selected module." : undefined}
            action={
              hasFilters ? (
                <Button variant="secondary" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="matrix-wrap">
            <table className="matrix">
              <caption className="sr-only">Permissions by role</caption>
              <thead>
                <tr>
                  <th scope="col">Permission</th>
                  {shownRoles.map((role) => (
                    <th key={role.id} scope="col">
                      <span className="matrix__role">
                        {role.name}
                        <small>
                          {grants[roleList.indexOf(role)]?.isLoading
                            ? "Loading…"
                            : role.code === SUPER_ADMIN
                              ? "Protected"
                              : saved[role.id]
                                ? `${formatNumber(saved[role.id]!.size)} granted`
                                : "Unavailable"}
                        </small>
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((group) => (
                  <Fragment key={group.module}>
                    <tr className="matrix__group">
                      <td className="matrix__group-cell">
                        <span className="matrix__group-title">
                          <span className="permission-group__icon" aria-hidden="true">
                            <Icon name={MODULE_ICONS[group.module] ?? "key"} size={14} />
                          </span>
                          <span>
                            <h3>{permissionModuleLabel(group.module)}</h3>
                            {PERMISSION_MODULES[group.module] ? <span className="meta">{PERMISSION_MODULES[group.module].description}</span> : null}
                          </span>
                        </span>
                      </td>
                      {shownRoles.map((role) => {
                        const ids = group.permissions.map((item) => item.id);
                        const granted = ids.filter((id) => isGranted(role, id)).length;
                        const all = granted === ids.length;
                        return (
                          <td key={role.id}>
                            {saved[role.id] ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={isLocked(role)}
                                onClick={() => setCells(role, ids, !all)}
                                aria-label={`${all ? "Revoke" : "Grant"} all ${permissionModuleLabel(group.module)} permissions for ${role.name}`}
                                title={isLocked(role) ? undefined : all ? "Revoke all in module" : "Grant all in module"}
                              >
                                {granted}/{ids.length}
                              </Button>
                            ) : grants[roleList.indexOf(role)]?.isLoading ? (
                              <Skeleton width={28} height={10} style={{ margin: "0 auto" }} />
                            ) : null}
                          </td>
                        );
                      })}
                    </tr>
                    {group.permissions.map((item: Permission) => {
                      const description = permissionDescription(item);
                      return (
                        <tr key={item.id}>
                          <th scope="row">
                            <span className="matrix__perm">
                              <strong>{item.name}</strong>
                              {description ? <small>{description}</small> : null}
                            </span>
                          </th>
                          {shownRoles.map((role) => {
                            const on = isGranted(role, item.id);
                            const changed = changes[role.id]?.[item.id] !== undefined;
                            if (!saved[role.id]) {
                              return (
                                <td key={role.id}>
                                  <span className="cell-muted">—</span>
                                </td>
                              );
                            }
                            return (
                              <td key={role.id}>
                                <button
                                  type="button"
                                  role="checkbox"
                                  aria-checked={on}
                                  aria-label={`${item.name} for ${role.name}`}
                                  className={`matrix-toggle${changed ? " is-changed" : ""}`}
                                  disabled={isLocked(role)}
                                  onClick={() => setCells(role, [item.id], !on)}
                                >
                                  <Icon name="check" size={14} />
                                </button>
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pending > 0 ? (
        <div className="matrix-savebar" role="status">
          <Icon name="warning" size={18} />
          <p>
            <strong>{pluralize(pending, "unsaved change")}</strong> across {pluralize(Object.keys(changes).length, "role")}. Save to apply
            them, or discard.
          </p>
          <Button variant="secondary" size="sm" onClick={() => setChanges({})} disabled={mutation.isPending}>
            Discard
          </Button>
          <Button variant="primary" size="sm" onClick={() => mutation.mutate()} loading={mutation.isPending} loadingText="Saving…">
            Save changes
          </Button>
        </div>
      ) : null}
    </div>
  );
}
