import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm, type UseFormRegister } from "react-hook-form";

import type { DeliveryMemberStatusAction } from "../../api/delivery-team.api";
import {
  changeDeliveryUserStatus,
  createDeliveryUser,
  getDeliveryUser,
  listAvailableDeliveryUsers,
  listDeliveryUsers,
  updateDeliveryUser,
  type AdminDeliveryUser
} from "../../api/delivery-users.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ConfirmationDialog, Drawer, DrawerSection, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { applyServerErrors, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary } from "../../components/forms/FormParts";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatDateTime, formatNumber, formatRelativeTime, todayInputValue } from "../../utils/format";
import { formatMobileNumber } from "../../utils/mobile";
import {
  DELIVERY_CREATE_FIELDS,
  DELIVERY_FIELD_LABELS,
  deliveryCreateSchema,
  deliveryUpdateSchema,
  emptyDeliveryCreate,
  memberToUpdateValues,
  toDeliveryCreateInput,
  toDeliveryUpdateInput,
  type DeliveryCreateValues,
  type DeliveryUpdateValues
} from "../delivery-team/delivery-schema";
import { DeliveryMemberFields } from "../delivery-team/DeliveryMemberFields";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "type", "status", "search"] as const;

const DRIVER_STATUS_TABS = [
  { value: "", label: "All Drivers" },
  { value: "ACTIVE", label: "Active" },
  { value: "PENDING_APPROVAL", label: "Pending approval" },
  { value: "BLOCKED", label: "Blocked" }
];

const STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "PENDING_APPROVAL", label: "Pending approval" },
  { value: "INACTIVE", label: "Inactive" },
  { value: "BLOCKED", label: "Blocked" }
];

/** A licence within 30 days of expiry is worth flagging before it stops a driver being assigned. */
function licenceState(member: AdminDeliveryUser): "expired" | "soon" | null {
  if (member.delivery_user_type !== "DRIVER" || !member.driving_license_expiry) return null;
  const expiry = member.driving_license_expiry.slice(0, 10);
  const today = todayInputValue();
  if (expiry <= today) return "expired";
  const soon = new Date();
  soon.setDate(soon.getDate() + 30);
  return expiry <= soon.toISOString().slice(0, 10) ? "soon" : null;
}

function DutyBadge({ onDuty }: { onDuty?: boolean }) {
  return onDuty ? <Badge tone="success">On duty</Badge> : <Badge tone="neutral">Off duty</Badge>;
}

export function AdminDeliveryUsersPage() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage, clearFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const merchantId = values.merchant;
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<{ member: AdminDeliveryUser; action: DeliveryMemberStatusAction } | null>(null);

  // If user navigates to ?type=HELPER or any helper query, normalize it away immediately
  useEffect(() => {
    if (values.type === "HELPER" || values.type) {
      setFilter("type", "");
    }
  }, [values.type, setFilter]);

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  // Crew belong to a merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter]);

  const params = {
    merchantId,
    delivery_user_type: "DRIVER",
    status: values.status || undefined,
    search: values.search || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.deliveryUsers.list(params),
    queryFn: ({ signal }) => listDeliveryUsers(params, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData
  });
  const availableDrivers = useQuery({
    queryKey: queryKeys.deliveryUsers.available(merchantId, "DRIVER"),
    queryFn: ({ signal }) => listAvailableDeliveryUsers(merchantId, "DRIVER", signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000,
    retry: false
  });
  // Totals for the cards, independent of the filters below.
  const allParams = { merchantId, limit: 100, offset: 0 };
  const everyone = useQuery({
    queryKey: queryKeys.deliveryUsers.list(allParams),
    queryFn: ({ signal }) => listDeliveryUsers(allParams, signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.deliveryUsers.all });
  }

  const statusMutation = useMutation({
    mutationFn: ({ member, action }: { member: AdminDeliveryUser; action: DeliveryMemberStatusAction }) =>
      changeDeliveryUserStatus(merchantId, member.id, action),
    onSuccess: (updated, { action }) => {
      const name = updated.full_name ?? "The crew member";
      toast.success(action === "block" ? `${name} has been blocked.` : `${name} can use the Delivery app again.`);
      invalidate();
    }
  });

  function statusActions(member: AdminDeliveryUser) {
    const blocked = member.status === "BLOCKED";
    return [
      {
        label: blocked ? "Unblock" : "Activate",
        icon: "unlock" as const,
        hidden: member.status === "ACTIVE" || !auth.can(PERMISSIONS.deliveryUsersActivate),
        onSelect: () => setPendingStatus({ member, action: blocked ? "unblock" : "activate" })
      },
      {
        label: "Block",
        icon: "ban" as const,
        danger: true,
        hidden: blocked || !auth.can(PERMISSIONS.deliveryUsersBlock),
        onSelect: () => setPendingStatus({ member, action: "block" })
      }
    ];
  }

  const all = everyone.data?.items ?? [];
  const allDrivers = all.filter((m) => m.delivery_user_type !== "HELPER");
  const onDutyCount = allDrivers.filter((m) => m.on_duty).length;
  const licenceIssues = allDrivers.filter((m) => licenceState(m) !== null).length;
  const filtered = Boolean(values.status || values.search);
  const displayedItems = (query.data?.items ?? []).filter((m) => m.delivery_user_type !== "HELPER");

  const columns: Column<AdminDeliveryUser>[] = [
    {
      key: "member",
      header: "Driver",
      primary: true,
      sortValue: (m) => m.full_name ?? "",
      render: (m) => (
        <div className="cell-primary">
          <UserAvatar name={m.full_name} />
          <div className="cell-primary__text">
            <button type="button" className="btn--link cell-primary__title" onClick={() => setOpenId(m.id)}>
              {m.full_name ?? "Unnamed Driver"}
            </button>
            <span className="cell-primary__subtitle nowrap">
              Driver{m.employee_code ? ` · ${m.employee_code}` : ""}
            </span>
          </div>
        </div>
      )
    },
    { key: "mobile", header: "Mobile", render: (m) => <span className="nowrap">{formatMobileNumber(m.mobile_number) || "—"}</span> },
    {
      key: "licence",
      header: "Licence",
      hideOnMobile: true,
      sortValue: (m) => m.driving_license_expiry ?? "",
      render: (m) => {
        const state = licenceState(m);
        return (
          <div className="cell-stack">
            <span className="mono nowrap">{m.driving_license_number || "—"}</span>
            <small
              className="nowrap"
              style={state ? { color: state === "expired" ? "var(--red-600, #dc2626)" : "var(--amber-600, #d97706)", fontWeight: 600 } : undefined}
            >
              {m.driving_license_expiry ? `${state === "expired" ? "Expired" : "Expires"} ${formatDate(m.driving_license_expiry)}` : "No expiry date"}
            </small>
          </div>
        );
      }
    },
    { key: "duty", header: "Duty", sortValue: (m) => (m.on_duty ? 1 : 0), render: (m) => <DutyBadge onDuty={m.on_duty} /> },
    { key: "status", header: "Status", sortValue: (m) => m.status, render: (m) => <StatusBadge status={m.status} /> }
  ];

  return (
    <div className="page admin-delivery-users-page">
      <PageHeader
        title="Delivery drivers"
        documentTitle="Delivery drivers"
        description="Drivers who sign in to the MBGA Delivery app, for each merchant."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            <Field label="Merchant" hideLabel>
              <Select
                value={merchantId}
                onChange={(event) => {
                  setOpenId(null);
                  setFilter("merchant", event.target.value);
                }}
                placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                disabled={merchants.isLoading}
                options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
              />
            </Field>
            {auth.can(PERMISSIONS.deliveryUsersCreate) ? (
              <Button icon="userPlus" onClick={() => setAdding(true)} disabled={!merchantId}>
                Add driver
              </Button>
            ) : null}
          </>
        }
      />

      {merchants.error ? <InlineError error={merchants.error} title="Merchants could not be loaded" onRetry={() => void merchants.refetch()} /> : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState icon="store" title="Choose a merchant" description="Crew belong to a merchant. Pick one above." />
          </Card>
        )
      ) : (
        <>
          <div className="kpi-grid" aria-label="Drivers summary">
            <StatCard
              label="Drivers"
              icon="truck"
              tone="blue"
              value={everyone.data ? formatNumber(allDrivers.length) : "—"}
              hint={availableDrivers.data ? `${formatNumber(availableDrivers.data.items.length)} assignable now` : "On the team"}
            />
            <StatCard
              label="Available now"
              icon="checkCircle"
              tone="green"
              value={availableDrivers.data ? formatNumber(availableDrivers.data.items.length) : "—"}
              hint="Active, approved & on duty"
            />
            <StatCard
              label="On duty"
              icon="activity"
              tone="violet"
              value={everyone.data ? formatNumber(onDutyCount) : "—"}
              hint="Clocked on in Delivery app"
            />
            <StatCard
              label="Licence attention"
              icon="warning"
              tone={licenceIssues ? "amber" : "slate"}
              value={everyone.data ? formatNumber(licenceIssues) : "—"}
              hint="Expired or expiring within 30 days"
            />
          </div>

          <Card bodyless className="table-card">
            <div className="status-tabs status-tabs--card" role="tablist" aria-label="Driver status">
              {DRIVER_STATUS_TABS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="tab"
                  aria-selected={values.status === item.value}
                  onClick={() => setFilter("status", item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <TableHeader
              title={DRIVER_STATUS_TABS.find((t) => t.value === values.status)?.label ?? "Drivers"}
              count={displayedItems.length}
              description="Select a driver to view and edit their profile and driving license details."
            />
            <FilterBar onReset={() => clearFilters(["status", "search"])} canReset={filtered}>
              <SearchInput label="Search drivers" placeholder="Name, mobile or employee code" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
              <Field label="Status" hideLabel>
                <Select value={values.status} onChange={(e) => setFilter("status", e.target.value)} placeholder="Any status" options={STATUS_OPTIONS} />
              </Field>
            </FilterBar>

            <DataTable
              caption="Delivery drivers"
              columns={columns}
              rows={displayedItems}
              getRowKey={(m) => m.id}
              onRowClick={(m) => setOpenId(m.id)}
              rowLabel={(m) => m.full_name ?? m.id}
              rowActions={(m) => [{ label: "View details", icon: "eye", onSelect: () => setOpenId(m.id) }, ...statusActions(m)]}
              isLoading={query.isLoading}
              error={query.data ? undefined : query.error}
              onRetry={() => void query.refetch()}
              empty={
                filtered ? (
                  <EmptyState icon="search" title="No drivers match" description="Try a different name or status." />
                ) : (
                  <EmptyState
                    icon="truck"
                    title="No drivers yet"
                    description="Add drivers so orders can be assigned to them."
                    action={auth.can(PERMISSIONS.deliveryUsersCreate) ? <Button icon="userPlus" onClick={() => setAdding(true)}>Add driver</Button> : undefined}
                  />
                )
              }
              footer={<Pagination page={page} pageSize={PAGE_SIZE} total={displayedItems.length} onPageChange={setPage} itemLabel="drivers" disabled={query.isFetching} />}
            />
          </Card>
        </>
      )}

      {openId && merchantId ? (
        <MemberDrawer
          merchantId={merchantId}
          memberId={openId}
          canEdit={auth.can(PERMISSIONS.deliveryUsersUpdate)}
          statusActions={statusActions}
          onClose={() => setOpenId(null)}
          onSaved={invalidate}
        />
      ) : null}

      {merchantId ? (
        <AddMemberDialog
          open={adding}
          merchantId={merchantId}
          onClose={() => setAdding(false)}
          onCreated={(member) => {
            toast.success(`${member.full_name ?? "The crew member"} has been added. They sign in with ${formatMobileNumber(member.mobile_number)}.`);
            invalidate();
            setOpenId(member.id);
          }}
        />
      ) : null}

      <ConfirmationDialog
        open={pendingStatus !== null}
        title={pendingStatus?.action === "block" ? `Block ${pendingStatus.member.full_name ?? "this crew member"}?` : `Reactivate ${pendingStatus?.member.full_name ?? "this crew member"}?`}
        description={
          pendingStatus?.action === "block"
            ? "They are signed out of the Delivery app at once and cannot be assigned deliveries until unblocked."
            : "They will be able to sign in to the Delivery app and be assigned deliveries again."
        }
        confirmLabel={pendingStatus?.action === "block" ? "Block" : "Reactivate"}
        confirmVariant={pendingStatus?.action === "block" ? "danger" : "primary"}
        onClose={() => setPendingStatus(null)}
        onConfirm={() => (pendingStatus ? statusMutation.mutateAsync(pendingStatus) : undefined)}
      />
    </div>
  );
}

function MemberDrawer({
  merchantId,
  memberId,
  canEdit,
  statusActions,
  onClose,
  onSaved
}: {
  merchantId: string;
  memberId: string;
  canEdit: boolean;
  statusActions: (member: AdminDeliveryUser) => Array<{ label: string; hidden?: boolean; danger?: boolean; onSelect: () => void }>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.deliveryUsers.detail(merchantId, memberId),
    queryFn: ({ signal }) => getDeliveryUser(merchantId, memberId, signal)
  });
  const member = query.data;
  const [editing, setEditing] = useState(false);
  const isDriver = member?.delivery_user_type === "DRIVER";
  const original = member ? memberToUpdateValues(member) : null;

  const { register, handleSubmit, formState, setError, reset } = useForm<DeliveryUpdateValues>({
    resolver: zodResolver(deliveryUpdateSchema(isDriver)),
    values: original ?? undefined,
    mode: "onTouched"
  });
  const [formMessage, setFormMessage] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (values: DeliveryUpdateValues) => updateDeliveryUser(merchantId, memberId, toDeliveryUpdateInput(values, original!)),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.deliveryUsers.detail(merchantId, memberId), updated);
      toast.success("Details saved.");
      setEditing(false);
      onSaved();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, DELIVERY_CREATE_FIELDS))
  });

  const licence = member ? licenceState(member) : null;
  const visibleActions = member ? statusActions(member).filter((a) => !a.hidden) : [];

  return (
    <Drawer
      open
      size="lg"
      title={member?.full_name ?? "Driver"}
      subtitle={member ? `Driver${member.employee_code ? ` · ${member.employee_code}` : ""}` : undefined}
      meta={
        member ? (
          <span className="row" style={{ gap: 6 }}>
            <StatusBadge status={member.status} />
            <DutyBadge onDuty={member.on_duty} />
          </span>
        ) : undefined
      }
      onClose={onClose}
      footer={
        member && !editing ? (
          <>
            {visibleActions.map((action) => (
              <Button key={action.label} variant={action.danger ? "danger" : "secondary"} onClick={action.onSelect}>
                {action.label}
              </Button>
            ))}
            {canEdit ? (
              <Button icon="edit" onClick={() => setEditing(true)}>
                Edit details
              </Button>
            ) : null}
          </>
        ) : undefined
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading crew member" />
      ) : query.error || !member ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : editing ? (
        <form
          className="stack-lg"
          noValidate
          onSubmit={handleSubmit((values) => {
            setFormMessage(null);
            mutation.mutate(values);
          })}
        >
          <FormErrorSummary errors={formState.errors} labels={DELIVERY_FIELD_LABELS} message={formMessage} />
          <DeliveryMemberFields
            register={register as unknown as UseFormRegister<DeliveryCreateValues>}
            errors={formState.errors}
            isDriver={isDriver}
            mode="edit"
            disabled={mutation.isPending}
          />
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <Button
              variant="secondary"
              onClick={() => {
                reset(original ?? undefined);
                setFormMessage(null);
                setEditing(false);
              }}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" icon="check" loading={mutation.isPending} loadingText="Saving…" disabled={!formState.isDirty}>
              Save changes
            </Button>
          </div>
        </form>
      ) : (
        <>
          {licence === "expired" ? (
            <Alert tone="error" title="Driving licence has expired">
              This driver cannot be assigned deliveries until the licence details are updated.
            </Alert>
          ) : licence === "soon" ? (
            <Alert tone="warning" title="Licence expires soon">
              Expires {formatDate(member.driving_license_expiry)}. Ask for the renewed licence.
            </Alert>
          ) : null}
          <DrawerSection title="Contact">
            <DetailsPanel
              items={[
                { label: "Mobile (sign-in)", value: formatMobileNumber(member.mobile_number) || "—" },
                { label: "Email", value: member.email || "—" },
                { label: "Address", value: member.address || "—" }
              ]}
            />
          </DrawerSection>
          {isDriver ? (
            <DrawerSection title="Driving licence">
              <DetailsPanel
                items={[
                  { label: "Number", value: member.driving_license_number ? <span className="mono">{member.driving_license_number}</span> : "—" },
                  { label: "Expiry", value: member.driving_license_expiry ? formatDate(member.driving_license_expiry) : "—" }
                ]}
              />
            </DrawerSection>
          ) : null}
          <DrawerSection title="Account">
            <DetailsPanel
              items={[
                { label: "Status", value: <StatusBadge status={member.status} /> },
                { label: "Approval", value: <StatusBadge status={member.approval_status} /> },
                { label: "Duty", value: <DutyBadge onDuty={member.on_duty} /> },
                { label: "App", value: member.allowed_channel === "DELIVERY" ? "Delivery app" : member.allowed_channel },
                { label: "Added", value: `${formatDateTime(member.created_at)} · ${formatRelativeTime(member.created_at)}` }
              ]}
            />
          </DrawerSection>
        </>
      )}
    </Drawer>
  );
}

function AddMemberDialog({
  open,
  merchantId,
  onClose,
  onCreated
}: {
  open: boolean;
  merchantId: string;
  onClose: () => void;
  onCreated: (member: AdminDeliveryUser) => void;
}) {
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError, reset } = useForm<DeliveryCreateValues>({
    resolver: zodResolver(deliveryCreateSchema),
    defaultValues: emptyDeliveryCreate("DRIVER"),
    mode: "onTouched"
  });

  useEffect(() => {
    if (open) {
      reset(emptyDeliveryCreate("DRIVER"));
      setFormMessage(null);
    }
  }, [open, reset]);

  const mutation = useMutation({
    mutationFn: (values: DeliveryCreateValues) =>
      createDeliveryUser(merchantId, toDeliveryCreateInput({ ...values, delivery_user_type: "DRIVER" })),
    onSuccess: (member) => {
      onCreated(member);
      onClose();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, DELIVERY_CREATE_FIELDS))
  });

  const submit = handleSubmit((values) => {
    setFormMessage(null);
    mutation.mutate(values);
  });

  return (
    <Modal
      open={open}
      wide
      title="Add driver"
      description="Drivers sign in to the MBGA Delivery app with their mobile number to receive deliveries."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={() => void submit()} loading={mutation.isPending} loadingText="Adding…">
            Add driver
          </Button>
        </>
      }
    >
      <form
        className="stack-lg"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <FormErrorSummary errors={formState.errors} labels={DELIVERY_FIELD_LABELS} message={formMessage} />
        <DeliveryMemberFields register={register} errors={formState.errors} isDriver={true} mode="create" disabled={mutation.isPending} />
      </form>
    </Modal>
  );
}

export default AdminDeliveryUsersPage;
