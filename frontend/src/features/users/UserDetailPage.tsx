import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { listPermissionsGrouped } from "../../api/permissions.api";
import { queryKeys } from "../../api/query-keys";
import { listRoles } from "../../api/roles.api";
import {
  assignUserRole,
  getUser,
  getUserAllowedChannels,
  getUserEffectivePermissions,
  listUserRoles,
  removeUserRole,
  updateUser,
  type User,
  type UserRoleAssignment
} from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Button } from "../../components/common/Button";
import { Menu } from "../../components/common/Menu";
import { Tabs } from "../../components/common/Tabs";
import { ConfirmationDialog, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { DataTable, type Column } from "../../components/tables/DataTable";
import { optionalEmailSchema, requiredText } from "../../schemas/common";
import { emptyToNull, formatDate, formatDateTime, humanize } from "../../utils/format";
import { CHANNELS, channelLabel, permissionModuleLabel, permissionModuleOrder, roleLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { useUserStatusActions } from "./useUserActions";
import { userDisplayName } from "./user-utils";

const editSchema = z.object({
  full_name: requiredText("the full name", 2, 160),
  email: optionalEmailSchema
});
type EditValues = z.infer<typeof editSchema>;

function EditUserDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError } = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { full_name: user.full_name ?? "", email: user.email ?? "" }
  });
  const mutation = useMutation({
    mutationFn: (values: EditValues) =>
      updateUser(user.id, {
        full_name: values.full_name.trim(),
        email: emptyToNull(values.email)?.toLowerCase() ?? null
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.users.detail(user.id), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("User details saved.");
      onClose();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["full_name", "email"]))
  });
  return (
    <Modal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title="Edit user details"
      description="The sign-in mobile number cannot be changed here."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="edit-user-form" variant="primary" loading={mutation.isPending} loadingText="Saving…">
            Save changes
          </Button>
        </>
      }
    >
      <form
        id="edit-user-form"
        className="stack"
        noValidate
        onSubmit={handleSubmit((values) => {
          setFormMessage(null);
          mutation.mutate(values);
        })}
      >
        {formMessage ? <Alert tone="error">{formMessage}</Alert> : null}
        <Field label="Full name" required error={fieldError(formState.errors, "full_name")}>
          <Input autoComplete="name" {...register("full_name")} />
        </Field>
        <Field label="Email address" optional error={fieldError(formState.errors, "email")}>
          <Input type="email" autoComplete="email" {...register("email")} />
        </Field>
      </form>
    </Modal>
  );
}

function useActiveRoles(enabled: boolean) {
  const params = { is_active: true, page: 1, page_size: 100 };
  return useQuery({
    queryKey: queryKeys.roles.list(params),
    queryFn: ({ signal }) => listRoles(params, signal),
    enabled,
    staleTime: 5 * 60_000
  });
}

function AssignRoleDialog({
  user,
  assigned,
  onClose
}: {
  user: User;
  assigned: UserRoleAssignment[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const roles = useActiveRoles(true);
  const [roleId, setRoleId] = useState("");
  const [error, setError] = useState<string | undefined>();
  const activeGlobal = new Set(assigned.filter((item) => item.is_active && item.scope_type === "global").map((item) => item.role_id));
  const options = (roles.data?.items ?? [])
    .filter((role) => !activeGlobal.has(role.id))
    .map((role) => ({ value: role.id, label: role.name }));

  const mutation = useMutation({
    mutationFn: () => assignUserRole(user.id, roleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(user.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Role assigned.");
      onClose();
    },
    onError: (caught) => setError(applyServerErrors(caught, () => undefined, []))
  });

  return (
    <Modal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title="Assign a role"
      description={`The role decides which panels ${userDisplayName(user)} can use and what they can do there.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              if (!roleId) {
                setError("Choose a role to assign.");
                return;
              }
              setError(undefined);
              mutation.mutate();
            }}
            loading={mutation.isPending}
            loadingText="Assigning…"
          >
            Assign role
          </Button>
        </>
      }
    >
      {roles.error ? (
        <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
      ) : (
        <div className="stack">
          <Field label="Role" required error={error} hint="Only active roles can be assigned.">
            <Select
              value={roleId}
              onChange={(event) => setRoleId(event.target.value)}
              options={options}
              placeholder={roles.isLoading ? "Loading roles…" : "Choose a role"}
              disabled={roles.isLoading}
            />
          </Field>
          <p className="meta">This assigns the role across MBGA. Merchant staff roles are managed from the merchant’s page.</p>
        </div>
      )}
    </Modal>
  );
}

function RolesTab({ user }: { user: User }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [assigning, setAssigning] = useState(false);
  const [removing, setRemoving] = useState<UserRoleAssignment | null>(null);
  const query = useQuery({
    queryKey: queryKeys.users.roles(user.id),
    queryFn: ({ signal }) => listUserRoles(user.id, signal)
  });
  const roles = useActiveRoles(auth.can(PERMISSIONS.rolesView));
  const roleName = (assignment: UserRoleAssignment) =>
    roles.data?.items.find((role) => role.id === assignment.role_id)?.name ?? roleLabel(assignment.role_code);

  const removeMutation = useMutation({
    mutationFn: (assignment: UserRoleAssignment) => removeUserRole(user.id, assignment.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(user.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Role removed.");
    }
  });

  const columns: Column<UserRoleAssignment>[] = [
    {
      key: "role",
      header: "Role",
      primary: true,
      render: (assignment) =>
        auth.can(PERMISSIONS.rolesView) ? (
          <Link to={`/admin/roles/${assignment.role_id}`} className="cell-primary__title">
            {roleName(assignment)}
          </Link>
        ) : (
          <span className="cell-primary__title">{roleName(assignment)}</span>
        )
    },
    {
      key: "scope",
      header: "Applies to",
      render: (assignment) =>
        assignment.scope_type === "merchant" ? (
          auth.can(PERMISSIONS.merchantsView) ? (
            <Link to={`/admin/merchants/${assignment.scope_id}`}>One merchant</Link>
          ) : (
            "One merchant"
          )
        ) : assignment.scope_type === "global" ? (
          "All of MBGA"
        ) : (
          humanize(assignment.scope_type)
        )
    },
    {
      key: "status",
      header: "Status",
      render: (assignment) => <StatusBadge status={assignment.is_active ? "ACTIVE" : "INACTIVE"} />
    },
    { key: "assigned", header: "Assigned on", render: (assignment) => <span className="nowrap">{formatDate(assignment.assigned_at)}</span> },
    {
      key: "until",
      header: "Ends",
      render: (assignment) => (assignment.valid_until ? formatDate(assignment.valid_until) : "No end date")
    }
  ];

  return (
    <Card
      bodyless
      className="table-card"
      title="Assigned roles"
      actions={
        auth.can(PERMISSIONS.usersAssignRoles) && auth.can(PERMISSIONS.rolesView) ? (
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setAssigning(true)}>
            Assign role
          </Button>
        ) : undefined
      }
    >
      <DataTable
        caption="Assigned roles"
        columns={columns}
        rows={query.data}
        getRowKey={(assignment) => assignment.id}
        rowLabel={roleName}
        rowActions={
          auth.can(PERMISSIONS.usersRemoveRoles)
            ? (assignment) => [
                {
                  label: "Remove role",
                  icon: "trash",
                  danger: true,
                  hidden: !assignment.is_active || (assignment.role_code === "super_admin" && auth.user?.user_id === user.id),
                  onSelect: () => setRemoving(assignment)
                }
              ]
            : undefined
        }
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        empty={
          <EmptyState
            icon="shield"
            title="No roles assigned"
            description="Without a role this user cannot sign in to any panel or app."
          />
        }
      />
      {assigning && query.data ? <AssignRoleDialog user={user} assigned={query.data} onClose={() => setAssigning(false)} /> : null}
      <ConfirmationDialog
        open={removing !== null}
        title={`Remove the ${removing ? roleName(removing) : ""} role?`}
        description={`${userDisplayName(user)} will lose the access this role gives, including any panels it allows them to sign in to.`}
        confirmLabel="Remove role"
        onClose={() => setRemoving(null)}
        onConfirm={() => (removing ? removeMutation.mutateAsync(removing) : undefined)}
      />
    </Card>
  );
}

function AccessTab({ user }: { user: User }) {
  const auth = useAuth();
  const [channel, setChannel] = useState("ADMIN");
  const channels = useQuery({
    queryKey: queryKeys.users.channels(user.id),
    queryFn: ({ signal }) => getUserAllowedChannels(user.id, signal)
  });
  const permissions = useQuery({
    queryKey: queryKeys.users.permissions(user.id, channel),
    queryFn: ({ signal }) => getUserEffectivePermissions(user.id, channel, signal)
  });
  const catalogue = useQuery({
    queryKey: queryKeys.permissions.grouped(),
    queryFn: ({ signal }) => listPermissionsGrouped(signal),
    enabled: auth.can(PERMISSIONS.permissionsView),
    staleTime: 10 * 60_000
  });
  const names = new Map<string, string>();
  catalogue.data?.groups.forEach((group) => group.permissions.forEach((item) => names.set(item.code, item.name)));

  const grouped = new Map<string, string[]>();
  (permissions.data?.permissions ?? []).forEach((code) => {
    const module = code.split(".")[0] ?? code;
    grouped.set(module, [...(grouped.get(module) ?? []), code]);
  });
  const modules = [...grouped.keys()].sort((a, b) => permissionModuleOrder(a) - permissionModuleOrder(b));

  return (
    <div className="stack-lg">
      <Card title="Panels this user can sign in to">
        {channels.isLoading ? (
          <LoadingSkeleton rows={1} />
        ) : channels.error ? (
          <ErrorState error={channels.error} onRetry={() => void channels.refetch()} />
        ) : channels.data && channels.data.channels.length > 0 ? (
          <div className="chip-list">
            {channels.data.channels.map((code) => (
              <Badge key={code} tone="info">
                {channelLabel(code)}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-muted">
            None. The account is not active, or no active role allows signing in to a panel.
          </p>
        )}
      </Card>

      <Card
        title="What this user can do"
        actions={
          <Field label="Panel" hideLabel>
            <Select value={channel} onChange={(event) => setChannel(event.target.value)} options={CHANNELS.map((item) => ({ value: item.code, label: item.label }))} />
          </Field>
        }
      >
        {permissions.isLoading ? (
          <LoadingSkeleton rows={3} />
        ) : permissions.error ? (
          <ErrorState error={permissions.error} onRetry={() => void permissions.refetch()} />
        ) : modules.length === 0 ? (
          <EmptyState
            icon="lock"
            title={`No access in the ${channelLabel(channel)}`}
            description="This user’s roles do not give any permissions here."
          />
        ) : (
          <div>
            {modules.map((module) => (
              <div key={module} className="permission-group">
                <div className="permission-group__header">
                  <h3 className="text-small" style={{ fontWeight: 650 }}>
                    {permissionModuleLabel(module)}
                  </h3>
                  <span className="meta">{grouped.get(module)?.length} allowed</span>
                </div>
                <ul className="permission-group__items list-plain">
                  {(grouped.get(module) ?? []).map((code) => (
                    <li key={code} className="row text-small" style={{ flexWrap: "nowrap" }}>
                      <span style={{ color: "var(--success-700)" }} aria-hidden="true">
                        ✓
                      </span>
                      {names.get(code) ?? humanize(code.split(".")[1] ?? code)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export function UserDetailPage() {
  const { userId = "" } = useParams();
  const auth = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const actions = useUserStatusActions();
  const query = useQuery({
    queryKey: queryKeys.users.detail(userId),
    queryFn: ({ signal }) => getUser(userId, signal)
  });
  const user = query.data;
  const tab = searchParams.get("tab") ?? "overview";
  const breadcrumbs = [
    { label: "Dashboard", to: "/admin/dashboard" },
    { label: "Users", to: "/admin/users" },
    { label: user ? userDisplayName(user) : "User" }
  ];

  if (query.isLoading) {
    return (
      <div className="page">
        <PageHeader title="User" breadcrumbs={breadcrumbs} />
        <Card>
          <LoadingSkeleton rows={4} label="Loading user" />
        </Card>
      </div>
    );
  }
  if (!user) {
    return (
      <div className="page">
        <PageHeader title="User" breadcrumbs={breadcrumbs} />
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const isSelf = auth.user?.user_id === user.id;
  const tabs = [
    {
      id: "overview",
      label: "Overview",
      content: (
        <Card title="Account details">
          <DetailsPanel
            items={[
              { label: "Full name", value: user.full_name },
              { label: "Mobile number", value: formatMobileNumber(user.mobile_number) },
              { label: "Email address", value: user.email },
              { label: "Username", value: user.username, hidden: !user.username },
              { label: "Account type", value: roleLabel(user.role) },
              { label: "Status", value: <StatusBadge status={user.status} /> },
              { label: "Added on", value: formatDateTime(user.created_at) }
            ]}
          />
        </Card>
      )
    },
    { id: "roles", label: "Roles", content: <RolesTab user={user} /> },
    ...(auth.can(PERMISSIONS.usersViewPermissions) ? [{ id: "access", label: "Access", content: <AccessTab user={user} /> }] : [])
  ];

  return (
    <div className="page">
      <PageHeader
        title={
          <span className="row" style={{ flexWrap: "nowrap" }}>
            <UserAvatar name={userDisplayName(user)} size="lg" />
            <span>{userDisplayName(user)}</span>
          </span>
        }
        documentTitle={userDisplayName(user)}
        breadcrumbs={breadcrumbs}
        meta={
          <>
            <StatusBadge status={user.status} />
            {isSelf ? <Badge tone="accent">This is you</Badge> : null}
            <RefreshIndicator active={query.isFetching} />
          </>
        }
        actions={
          <>
            {auth.can(PERMISSIONS.usersUpdate) ? (
              <Button variant="secondary" icon="edit" onClick={() => setEditing(true)}>
                Edit details
              </Button>
            ) : null}
            <Menu label="More account actions" actions={actions.actionsFor(user)} />
          </>
        }
      />
      {user.status === "BLOCKED" ? (
        <Alert tone="warning" title="This account is blocked">
          This user cannot sign in until the account is unblocked.
        </Alert>
      ) : null}
      <Tabs
        label="User sections"
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
      {editing ? <EditUserDialog user={user} onClose={() => setEditing(false)} /> : null}
      {actions.dialog}
    </div>
  );
}
