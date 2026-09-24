import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  createMerchantUser,
  listMerchantUsers,
  updateMerchantUser,
  type Merchant,
  type MerchantUser
} from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ConfirmationDialog, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, PhoneInput } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { Card } from "../../components/layout/Page";
import { DataTable, type Column } from "../../components/tables/DataTable";
import { mobileSchema, optionalEmailSchema, requiredText } from "../../schemas/common";
import { emptyToNull, emptyToUndefined, formatDate } from "../../utils/format";
import { staffTypeLabel } from "../../utils/labels";
import { formatMobileNumber, normalizeMobileNumber } from "../../utils/mobile";

const addSchema = z.object({
  full_name: requiredText("the full name", 2, 160),
  mobile_number: mobileSchema,
  email: optionalEmailSchema
});
type AddValues = z.infer<typeof addSchema>;

const editSchema = z.object({
  full_name: requiredText("the full name", 2, 160),
  email: optionalEmailSchema
});
type EditValues = z.infer<typeof editSchema>;

function AddStaffDialog({ merchant, open, onClose }: { merchant: Merchant; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError, reset } = useForm<AddValues>({
    resolver: zodResolver(addSchema),
    defaultValues: { full_name: "", mobile_number: "", email: "" }
  });
  const mutation = useMutation({
    mutationFn: (values: AddValues) =>
      createMerchantUser(merchant.id, {
        full_name: values.full_name.trim(),
        mobile_number: normalizeMobileNumber(values.mobile_number) ?? values.mobile_number,
        email: emptyToUndefined(values.email)?.toLowerCase(),
        staff_type: "MANAGER"
      }),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.users(merchant.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(`${user.full_name ?? "The staff member"} can now sign in to the Merchant panel.`);
      close();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["full_name", "mobile_number", "email"]))
  });

  function close() {
    reset();
    setFormMessage(null);
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={close}
      busy={mutation.isPending}
      title="Add staff account"
      description={`The person will be able to sign in to the Merchant panel for ${merchant.business_name} as a manager.`}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="add-staff-form"
            variant="primary"
            loading={mutation.isPending}
            loadingText="Adding…"
          >
            Add staff account
          </Button>
        </>
      }
    >
      <form
        id="add-staff-form"
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
        <Field
          label="Mobile number"
          required
          error={fieldError(formState.errors, "mobile_number")}
          hint="Used to sign in with a verification code."
        >
          <PhoneInput {...register("mobile_number")} />
        </Field>
        <Field label="Email address" optional error={fieldError(formState.errors, "email")}>
          <Input type="email" autoComplete="email" {...register("email")} />
        </Field>
      </form>
    </Modal>
  );
}

function EditStaffDialog({ merchant, user, onClose }: { merchant: Merchant; user: MerchantUser; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError } = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { full_name: user.full_name ?? "", email: user.email ?? "" }
  });
  const mutation = useMutation({
    mutationFn: (values: EditValues) =>
      updateMerchantUser(merchant.id, user.user_id, {
        full_name: values.full_name.trim(),
        email: emptyToNull(values.email)?.toLowerCase() ?? null
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.users(merchant.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      toast.success("Staff details saved.");
      onClose();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, ["full_name", "email"]))
  });

  return (
    <Modal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title="Edit staff account"
      description={`Mobile number ${formatMobileNumber(user.mobile_number)} cannot be changed.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="edit-staff-form" variant="primary" loading={mutation.isPending} loadingText="Saving…">
            Save changes
          </Button>
        </>
      }
    >
      <form
        id="edit-staff-form"
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

export function MerchantStaffSection({ merchant }: { merchant: Merchant }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<MerchantUser | null>(null);
  const [toggling, setToggling] = useState<MerchantUser | null>(null);
  const canCreate = auth.can(PERMISSIONS.merchantUsersCreate);
  const canUpdate = auth.can(PERMISSIONS.merchantUsersUpdate);

  const query = useQuery({
    queryKey: queryKeys.merchants.users(merchant.id),
    queryFn: ({ signal }) => listMerchantUsers(merchant.id, signal)
  });

  const statusMutation = useMutation({
    mutationFn: (user: MerchantUser) =>
      updateMerchantUser(merchant.id, user.user_id, { status: user.status === "ACTIVE" ? "INACTIVE" : "ACTIVE" }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.users(merchant.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(
        updated.status === "ACTIVE"
          ? `${updated.full_name ?? "The staff member"} can sign in again.`
          : `${updated.full_name ?? "The staff member"} can no longer sign in for this merchant.`
      );
    }
  });

  const columns: Column<MerchantUser>[] = [
    {
      key: "name",
      header: "Name",
      primary: true,
      render: (user) => (
        <div className="cell-primary">
          <UserAvatar name={user.full_name} />
          <div className="cell-primary__text">
            <span className="cell-primary__title">{user.full_name ?? "Unnamed"}</span>
            <span className="cell-primary__subtitle">{user.email ?? "No email"}</span>
          </div>
        </div>
      )
    },
    { key: "mobile", header: "Mobile number", render: (user) => <span className="nowrap">{formatMobileNumber(user.mobile_number)}</span> },
    { key: "type", header: "Position", render: (user) => staffTypeLabel(user.staff_type) },
    { key: "status", header: "Status", render: (user) => <StatusBadge status={user.status} /> },
    { key: "added", header: "Added on", render: (user) => <span className="nowrap">{formatDate(user.created_at)}</span> }
  ];

  const deactivating = toggling?.status === "ACTIVE";

  return (
    <Card
      bodyless
      className="table-card"
      title="Staff accounts"
      actions={
        canCreate && merchant.status === "ACTIVE" ? (
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setAdding(true)}>
            Add staff account
          </Button>
        ) : undefined
      }
    >
      <DataTable
        caption="Staff accounts"
        columns={columns}
        rows={query.data}
        getRowKey={(user) => user.id}
        rowLabel={(user) => user.full_name ?? "staff member"}
        rowActions={
          canUpdate
            ? (user) => [
                { label: "Edit details", icon: "edit", onSelect: () => setEditing(user) },
                {
                  label: user.status === "ACTIVE" ? "Deactivate account" : "Activate account",
                  icon: user.status === "ACTIVE" ? "ban" : "unlock",
                  danger: user.status === "ACTIVE",
                  onSelect: () => setToggling(user)
                }
              ]
            : undefined
        }
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        empty={
          <EmptyState
            icon="users"
            title="No staff accounts"
            description="People added here can sign in to the Merchant panel for this business."
          />
        }
      />
      <AddStaffDialog merchant={merchant} open={adding} onClose={() => setAdding(false)} />
      {editing ? <EditStaffDialog merchant={merchant} user={editing} onClose={() => setEditing(null)} /> : null}
      <ConfirmationDialog
        open={toggling !== null}
        title={deactivating ? `Deactivate ${toggling?.full_name ?? "this account"}?` : `Activate ${toggling?.full_name ?? "this account"}?`}
        description={
          deactivating
            ? "This person will no longer be able to sign in to the Merchant panel for this business."
            : "This person will be able to sign in to the Merchant panel for this business again."
        }
        confirmLabel={deactivating ? "Deactivate account" : "Activate account"}
        confirmVariant={deactivating ? "danger" : "primary"}
        onClose={() => setToggling(null)}
        onConfirm={() => (toggling ? statusMutation.mutateAsync(toggling) : undefined)}
      />
    </Card>
  );
}
