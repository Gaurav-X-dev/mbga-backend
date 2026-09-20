import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { listPermissionsGrouped } from "../../api/permissions.api";
import { queryKeys } from "../../api/query-keys";
import {
  deleteRole,
  getRole,
  listRoleChannels,
  listRolePermissions,
  listRoleUsers,
  replaceRoleChannels,
  replaceRolePermissions,
  setRoleActive,
  type Role
} from "../../api/roles.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Menu, type MenuAction } from "../../components/common/Menu";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Tabs } from "../../components/common/Tabs";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Checkbox, SearchInput } from "../../components/forms/Field";
import { UnsavedChangesGuard } from "../../components/forms/FormParts";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { DataTable, type Column } from "../../components/tables/DataTable";
import { formatDate, pluralize } from "../../utils/format";
import { CHANNELS, PERMISSION_MODULES, permissionDescription, permissionModuleLabel, permissionModuleOrder, roleDescription } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import type { User } from "../../api/users.api";
import { RoleFormDialog } from "./RoleFormDialog";

const SUPER_ADMIN = "super_admin";

function PermissionsTab({ role }: { role: Role }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState("");
  const catalogue = useQuery({
    queryKey: queryKeys.permissions.grouped(),
    queryFn: ({ signal }) => listPermissionsGrouped(signal),
    enabled: auth.can(PERMISSIONS.permissionsView),
    staleTime: 10 * 60_000
  });
  const assigned = useQuery({
    queryKey: queryKeys.roles.permissions(role.id),
    queryFn: ({ signal }) => listRolePermissions(role.id, signal)
  });

  const initial = useMemo(() => new Set((assigned.data ?? []).map((item) => item.id)), [assigned.data]);
  const [selected, setSelected] = useState<Set<string>>(initial);
  useEffect(() => setSelected(new Set(initial)), [initial]);

  const isProtected = role.code === SUPER_ADMIN;
  const canEdit = auth.can(PERMISSIONS.rolesAssignPermissions) && auth.can(PERMISSIONS.permissionsView) && !isProtected;
  const dirty = selected.size !== initial.size || [...selected].some((id) => !initial.has(id));

  const mutation = useMutation({
    mutationFn: () => {
      // Keep assigned permissions that are not in the active catalogue (e.g. retired ones).
      const catalogueIds = new Set(catalogue.data?.groups.flatMap((group) => group.permissions.map((item) => item.id)));
      const hidden = [...initial].filter((id) => !catalogueIds.has(id));
      return replaceRolePermissions(role.id, [...new Set([...selected, ...hidden])]);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.permissions(role.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Permissions saved. Changes apply the next time affected users sign in or refresh.");
    }
  });

  if (assigned.isLoading || (catalogue.isLoading && catalogue.fetchStatus !== "idle")) {
    return <LoadingSkeleton rows={5} label="Loading permissions" />;
  }
  if (assigned.error) return <ErrorState error={assigned.error} onRetry={() => void assigned.refetch()} />;

  // Without catalogue access, show the assigned permissions read-only.
  const groups =
    catalogue.data?.groups ??
    Object.values(
      (assigned.data ?? []).reduce<Record<string, { module: string; permissions: NonNullable<typeof assigned.data> }>>(
        (acc, item) => {
          acc[item.module] ??= { module: item.module, permissions: [] };
          acc[item.module].permissions.push(item);
          return acc;
        },
        {}
      )
    );
  const term = filter.trim().toLowerCase();
  const visible = groups
    .map((group) => ({
      ...group,
      permissions: group.permissions.filter(
        (item) =>
          !term ||
          item.name.toLowerCase().includes(term) ||
          permissionModuleLabel(group.module).toLowerCase().includes(term)
      )
    }))
    .filter((group) => group.permissions.length > 0)
    .sort((a, b) => permissionModuleOrder(a.module) - permissionModuleOrder(b.module));

  function toggle(ids: string[], on: boolean) {
    setSelected((previous) => {
      const next = new Set(previous);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
  }

  return (
    <div className="stack">
      <UnsavedChangesGuard when={dirty && !mutation.isPending} />
      {isProtected ? (
        <Alert tone="info" title="Protected role">
          The Super Admin role always has full access. Its permissions cannot be changed.
        </Alert>
      ) : null}
      {catalogue.error ? <InlineError error={catalogue.error} onRetry={() => void catalogue.refetch()} /> : null}
      <div className="row-between">
        <SearchInput label="Filter permissions" placeholder="Filter permissions" value={filter} onChange={(event) => setFilter(event.target.value)} />
        <span className="meta" aria-live="polite">
          {pluralize(selected.size, "permission")} selected
        </span>
      </div>
      {visible.length === 0 ? (
        <EmptyState icon="key" title={term ? "No permissions match this filter" : "This role has no permissions yet"} />
      ) : (
        <div>
          {visible.map((group) => {
            const ids = group.permissions.map((item) => item.id);
            const count = ids.filter((id) => selected.has(id)).length;
            const moduleInfo = PERMISSION_MODULES[group.module];
            return (
              <fieldset key={group.module} className="permission-group" style={{ marginInline: 0, padding: 0, minWidth: 0 }}>
                <legend className="sr-only">{permissionModuleLabel(group.module)}</legend>
                <div className="permission-group__header">
                  <div>
                    <h3 className="text-small" style={{ fontWeight: 650 }}>
                      {permissionModuleLabel(group.module)}
                    </h3>
                    {moduleInfo ? <p className="meta">{moduleInfo.description}</p> : null}
                  </div>
                  <div className="row">
                    <span className="meta">
                      {count} of {ids.length}
                    </span>
                    {canEdit ? (
                      <Button variant="link" size="sm" onClick={() => toggle(ids, count !== ids.length)}>
                        {count === ids.length ? "Clear all" : "Select all"}
                        <span className="sr-only"> in {permissionModuleLabel(group.module)}</span>
                      </Button>
                    ) : null}
                  </div>
                </div>
                <div className="permission-group__items">
                  {group.permissions.map((item) => (
                    <Checkbox
                      key={item.id}
                      label={item.name}
                      description={permissionDescription(item)}
                      checked={selected.has(item.id) || isProtected}
                      disabled={!canEdit || mutation.isPending}
                      onChange={(event) => toggle([item.id], event.target.checked)}
                    />
                  ))}
                </div>
              </fieldset>
            );
          })}
        </div>
      )}
      {canEdit ? (
        <div className="form-actions form-actions--sticky">
          {mutation.error ? <InlineError error={mutation.error} /> : null}
          <Button variant="secondary" disabled={!dirty || mutation.isPending} onClick={() => setSelected(new Set(initial))}>
            Discard changes
          </Button>
          <Button variant="primary" disabled={!dirty} loading={mutation.isPending} loadingText="Saving…" onClick={() => mutation.mutate()}>
            Save permissions
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ChannelsTab({ role }: { role: Role }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useQuery({
    queryKey: queryKeys.roles.channels(role.id),
    queryFn: ({ signal }) => listRoleChannels(role.id, signal)
  });
  const initial = useMemo(
    () => new Set((query.data ?? []).filter((item) => item.is_allowed).map((item) => item.login_channel)),
    [query.data]
  );
  const [selected, setSelected] = useState<Set<string>>(initial);
  useEffect(() => setSelected(new Set(initial)), [initial]);
  const dirty = selected.size !== initial.size || [...selected].some((code) => !initial.has(code));
  const canEdit = auth.can(PERMISSIONS.rolesAssignChannels);
  const isProtected = role.code === SUPER_ADMIN;

  const mutation = useMutation({
    mutationFn: () =>
      replaceRoleChannels(
        role.id,
        CHANNELS.filter((channel) => selected.has(channel.code) || initial.has(channel.code)).map((channel) => ({
          login_channel: channel.code,
          is_allowed: selected.has(channel.code)
        }))
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.channels(role.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Panel access saved.");
    }
  });

  if (query.isLoading) return <LoadingSkeleton rows={2} />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <Card title="Where people with this role can sign in">
      <UnsavedChangesGuard when={dirty && !mutation.isPending} />
      <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
        <legend className="sr-only">Panels and apps</legend>
        {CHANNELS.map((channel) => {
          const locked = isProtected && channel.code === "ADMIN";
          return (
            <Checkbox
              key={channel.code}
              label={channel.label}
              description={locked ? `${channel.description}. Always allowed for Super Admin.` : channel.description}
              checked={selected.has(channel.code)}
              disabled={!canEdit || locked || mutation.isPending}
              onChange={(event) =>
                setSelected((previous) => {
                  const next = new Set(previous);
                  if (event.target.checked) next.add(channel.code);
                  else next.delete(channel.code);
                  return next;
                })
              }
            />
          );
        })}
      </fieldset>
      {canEdit ? (
        <div className="form-actions" style={{ marginTop: "var(--space-5)" }}>
          {mutation.error ? <InlineError error={mutation.error} /> : null}
          <Button variant="secondary" disabled={!dirty || mutation.isPending} onClick={() => setSelected(new Set(initial))}>
            Discard changes
          </Button>
          <Button variant="primary" disabled={!dirty} loading={mutation.isPending} loadingText="Saving…" onClick={() => mutation.mutate()}>
            Save panel access
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

function RoleUsersTab({ users, isLoading, error, onRetry }: { users?: User[]; isLoading: boolean; error: unknown; onRetry: () => void }) {
  const auth = useAuth();
  const columns: Column<User>[] = [
    {
      key: "name",
      header: "Name",
      primary: true,
      render: (user) => (
        <div className="cell-primary">
          <UserAvatar name={user.full_name} />
          <div className="cell-primary__text">
            {auth.can(PERMISSIONS.usersView) ? (
              <Link to={`/admin/users/${user.id}`} className="cell-primary__title">
                {user.full_name ?? "Unnamed user"}
              </Link>
            ) : (
              <span className="cell-primary__title">{user.full_name ?? "Unnamed user"}</span>
            )}
            <span className="cell-primary__subtitle">{user.email ?? "No email"}</span>
          </div>
        </div>
      )
    },
    { key: "mobile", header: "Mobile number", render: (user) => <span className="nowrap">{formatMobileNumber(user.mobile_number)}</span> },
    { key: "status", header: "Status", render: (user) => <StatusBadge status={user.status} /> },
    { key: "added", header: "Added on", render: (user) => formatDate(user.created_at) }
  ];
  return (
    <Card bodyless className="table-card" title="People with this role">
      <DataTable
        caption="People with this role"
        columns={columns}
        rows={users}
        getRowKey={(user) => user.id}
        isLoading={isLoading}
        error={error}
        onRetry={onRetry}
        empty={<EmptyState icon="users" title="Nobody has this role" description="Assign it from a user’s page." />}
      />
    </Card>
  );
}

export function RoleDetailPage() {
  const { roleId = "" } = useParams();
  const auth = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "activate" | "deactivate" | null>(null);

  const query = useQuery({
    queryKey: queryKeys.roles.detail(roleId),
    queryFn: ({ signal }) => getRole(roleId, signal)
  });
  const users = useQuery({
    queryKey: queryKeys.roles.users(roleId),
    queryFn: ({ signal }) => listRoleUsers(roleId, signal)
  });
  const role = query.data;

  const statusMutation = useMutation({
    mutationFn: (active: boolean) => setRoleActive(roleId, active),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.roles.detail(roleId), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(updated.is_active ? `${updated.name} is active.` : `${updated.name} has been deactivated.`);
    }
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteRole(roleId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.roles.detail(roleId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(`${role?.name ?? "The role"} has been deleted.`);
      navigate("/admin/roles", { replace: true });
    }
  });

  const breadcrumbs = [
    { label: "Dashboard", to: "/admin/dashboard" },
    { label: "Roles", to: "/admin/roles" },
    { label: role?.name ?? "Role" }
  ];

  if (query.isLoading) {
    return (
      <div className="page">
        <PageHeader title="Role" breadcrumbs={breadcrumbs} />
        <Card>
          <LoadingSkeleton rows={4} label="Loading role" />
        </Card>
      </div>
    );
  }
  if (!role) {
    return (
      <div className="page">
        <PageHeader title="Role" breadcrumbs={breadcrumbs} />
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const isProtected = role.code === SUPER_ADMIN;
  const userCount = users.data?.length;
  const menuActions: MenuAction[] = [
    {
      label: "Activate role",
      icon: "unlock",
      hidden: role.is_active || !auth.can(PERMISSIONS.rolesActivate),
      onSelect: () => setConfirm("activate")
    },
    {
      label: "Deactivate role",
      icon: "ban",
      danger: true,
      hidden: !role.is_active || isProtected || !auth.can(PERMISSIONS.rolesActivate),
      onSelect: () => setConfirm("deactivate")
    },
    {
      label: userCount ? "Delete role (remove its users first)" : "Delete role",
      icon: "trash",
      danger: true,
      disabled: users.isLoading || Boolean(userCount),
      hidden: role.is_system || !auth.can(PERMISSIONS.rolesDelete),
      onSelect: () => setConfirm("delete")
    }
  ];

  const tab = searchParams.get("tab") ?? "overview";
  const tabs = [
    {
      id: "overview",
      label: "Overview",
      content: (
        <Card title="Role details">
          <DetailsPanel
            items={[
              { label: "Name", value: role.name },
              { label: "Description", value: roleDescription(role) },
              { label: "Type", value: role.is_system ? "Built-in role" : "Custom role" },
              { label: "Status", value: <StatusBadge status={role.is_active ? "ACTIVE" : "INACTIVE"} /> },
              {
                label: "People with this role",
                value: users.isLoading ? "Loading…" : users.error ? "Not available" : pluralize(userCount ?? 0, "person", "people")
              },
              { label: "Role code", value: <span className="mono">{role.code}</span> }
            ]}
          />
        </Card>
      )
    },
    { id: "permissions", label: "Permissions", content: <PermissionsTab role={role} /> },
    { id: "panels", label: "Panel access", content: <ChannelsTab role={role} /> },
    {
      id: "users",
      label: `People${userCount !== undefined ? ` (${userCount})` : ""}`,
      content: (
        <RoleUsersTab users={users.data} isLoading={users.isLoading} error={users.error} onRetry={() => void users.refetch()} />
      )
    }
  ];

  const confirmCopy = {
    delete: {
      title: `Delete the ${role.name} role?`,
      description: "This permanently removes the role. This cannot be undone.",
      label: "Delete role",
      run: () => deleteMutation.mutateAsync()
    },
    deactivate: {
      title: `Deactivate the ${role.name} role?`,
      description: "People with this role will lose the access it gives until it is activated again.",
      label: "Deactivate role",
      run: () => statusMutation.mutateAsync(false)
    },
    activate: {
      title: `Activate the ${role.name} role?`,
      description: "People with this role will get the access it gives.",
      label: "Activate role",
      run: () => statusMutation.mutateAsync(true)
    }
  } as const;
  const current = confirm ? confirmCopy[confirm] : null;

  return (
    <div className="page">
      <PageHeader
        title={role.name}
        breadcrumbs={breadcrumbs}
        description={roleDescription(role)}
        meta={
          <>
            <StatusBadge status={role.is_active ? "ACTIVE" : "INACTIVE"} />
            {role.is_system ? <Badge tone="info">Built-in</Badge> : <Badge>Custom</Badge>}
            {isProtected ? <Badge tone="accent">Protected</Badge> : null}
            <RefreshIndicator active={query.isFetching} />
          </>
        }
        actions={
          <>
            {auth.can(PERMISSIONS.rolesUpdate) ? (
              <Button variant="secondary" icon="edit" onClick={() => setEditing(true)}>
                Edit role
              </Button>
            ) : null}
            <Menu label="More role actions" actions={menuActions} />
          </>
        }
      />
      {!role.is_active ? (
        <Alert tone="warning" title="This role is inactive">
          People with this role do not currently get any of its access, and it cannot be assigned.
        </Alert>
      ) : null}
      <Tabs
        label="Role sections"
        activeId={tab}
        onChange={(id) =>
          setSearchParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              if (id === "overview") next.delete("tab");
              else next.set("tab", id);
              return next;
            },
            { replace: true }
          )
        }
        tabs={tabs}
      />
      {editing ? <RoleFormDialog role={role} onClose={() => setEditing(false)} /> : null}
      <ConfirmationDialog
        open={current !== null}
        title={current?.title ?? ""}
        description={current?.description ?? ""}
        confirmLabel={current?.label ?? "Confirm"}
        confirmVariant={confirm === "activate" ? "primary" : "danger"}
        onClose={() => setConfirm(null)}
        onConfirm={() => current?.run()}
      />
    </div>
  );
}
