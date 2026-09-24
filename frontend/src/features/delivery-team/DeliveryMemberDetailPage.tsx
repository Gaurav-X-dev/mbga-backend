import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, type UseFormRegister } from "react-hook-form";
import { useParams } from "react-router-dom";

import { getDeliveryMember, updateDeliveryMember, type DeliveryMember } from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Menu } from "../../components/common/Menu";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Alert, ErrorState, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { applyServerErrors, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary, UnsavedChangesGuard } from "../../components/forms/FormParts";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatDate, formatDateTime } from "../../utils/format";
import { deliveryTypeLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { DeliveryMemberFields } from "./DeliveryMemberFields";
import {
  DELIVERY_FIELD_LABELS,
  deliveryUpdateSchema,
  memberToUpdateValues,
  toDeliveryUpdateInput,
  type DeliveryCreateValues,
  type DeliveryUpdateValues
} from "./delivery-schema";
import { useDeliveryMemberStatus } from "./useDeliveryMemberStatus";

function EditMemberForm({ member, onDone }: { member: DeliveryMember; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const isDriver = member.delivery_user_type === "DRIVER";
  const original = memberToUpdateValues(member);
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError } = useForm<DeliveryUpdateValues>({
    resolver: zodResolver(deliveryUpdateSchema(isDriver)),
    defaultValues: original,
    mode: "onTouched"
  });

  const mutation = useMutation({
    mutationFn: (values: DeliveryUpdateValues) => updateDeliveryMember(member.id, toDeliveryUpdateInput(values, original)),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.deliveryTeam.detail(member.id), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.deliveryTeam.lists() });
      toast.success("Team member details saved.");
      onDone();
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, Object.keys(original)))
  });

  return (
    <form
      className="stack-lg"
      noValidate
      onSubmit={handleSubmit((values) => {
        setFormMessage(null);
        if (Object.keys(toDeliveryUpdateInput(values, original)).length === 0) {
          onDone();
          return;
        }
        mutation.mutate(values);
      })}
    >
      <UnsavedChangesGuard when={formState.isDirty && !mutation.isPending && !mutation.isSuccess} />
      {formState.submitCount > 0 && (Object.keys(formState.errors).length > 0 || formMessage) ? (
        <FormErrorSummary errors={formState.errors} labels={DELIVERY_FIELD_LABELS} message={formMessage} />
      ) : null}
      <Alert tone="info">The mobile number and team member type cannot be changed.</Alert>
      <DeliveryMemberFields
        register={register as unknown as UseFormRegister<DeliveryCreateValues>}
        errors={formState.errors}
        isDriver={isDriver}
        mode="edit"
        disabled={mutation.isPending}
      />
      <div className="form-actions form-actions--sticky">
        <Button variant="secondary" onClick={onDone} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={mutation.isPending} loadingText="Saving…">
          Save changes
        </Button>
      </div>
    </form>
  );
}

export function DeliveryMemberDetailPage() {
  const { memberId = "" } = useParams();
  const auth = useAuth();
  const [editing, setEditing] = useState(false);
  const status = useDeliveryMemberStatus();
  const query = useQuery({
    queryKey: queryKeys.deliveryTeam.detail(memberId),
    queryFn: ({ signal }) => getDeliveryMember(memberId, signal)
  });
  const member = query.data;
  const breadcrumbs = [
    { label: "Dashboard", to: "/merchant/dashboard" },
    { label: "Delivery team", to: "/merchant/delivery-team" },
    { label: member?.full_name ?? "Team member" }
  ];

  if (query.isLoading) {
    return (
      <div className="page">
        <PageHeader title="Team member" breadcrumbs={breadcrumbs} />
        <Card>
          <LoadingSkeleton rows={4} label="Loading team member" />
        </Card>
      </div>
    );
  }
  if (!member) {
    return (
      <div className="page">
        <PageHeader title="Team member" breadcrumbs={breadcrumbs} />
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const isDriver = member.delivery_user_type === "DRIVER";
  const licenceExpired =
    isDriver && member.driving_license_expiry ? new Date(member.driving_license_expiry).getTime() < Date.now() : false;
  const statusActions = status.actionsFor(member);

  return (
    <div className="page">
      <PageHeader
        title={
          <span className="row" style={{ flexWrap: "nowrap" }}>
            <UserAvatar name={member.full_name} size="lg" />
            <span>{member.full_name ?? "Team member"}</span>
          </span>
        }
        documentTitle={member.full_name ?? "Team member"}
        breadcrumbs={breadcrumbs}
        meta={
          <>
            <StatusBadge status={member.status} />
            <Badge tone={isDriver ? "info" : "neutral"}>{deliveryTypeLabel(member.delivery_user_type)}</Badge>
            <span className="meta">Added {formatDate(member.created_at)}</span>
            <RefreshIndicator active={query.isFetching} />
          </>
        }
        actions={
          editing ? undefined : (
            <>
              {auth.can(PERMISSIONS.deliveryUsersUpdate) ? (
                <Button variant="secondary" icon="edit" onClick={() => setEditing(true)}>
                  Edit details
                </Button>
              ) : null}
              {statusActions.some((action) => !action.hidden) ? (
                <Menu label="More team member actions" actions={statusActions} />
              ) : null}
            </>
          )
        }
      />
      {member.status === "BLOCKED" ? (
        <Alert tone="warning" title="This team member is blocked">
          They cannot sign in to the Delivery app until unblocked.
        </Alert>
      ) : null}
      {licenceExpired ? (
        <Alert tone="warning" title="Driving licence has expired">
          Update the licence details before this driver goes out on deliveries.
        </Alert>
      ) : null}

      {editing ? (
        <EditMemberForm member={member} onDone={() => setEditing(false)} />
      ) : (
        <div className="stack-lg">
          <Card title="Personal details">
            <DetailsPanel
              items={[
                { label: "Full name", value: member.full_name },
                { label: "Mobile number", value: formatMobileNumber(member.mobile_number) },
                { label: "Email address", value: member.email },
                { label: "Employee code", value: member.employee_code },
                { label: "Address", value: member.address }
              ]}
            />
          </Card>
          {isDriver ? (
            <Card title="Driving licence">
              <DetailsPanel
                items={[
                  { label: "Licence number", value: member.driving_license_number },
                  { label: "Expiry date", value: member.driving_license_expiry ? formatDate(member.driving_license_expiry) : null }
                ]}
              />
            </Card>
          ) : null}
          <Card title="App access">
            <DetailsPanel
              items={[
                { label: "Account status", value: <StatusBadge status={member.status} /> },
                { label: "Approval", value: <StatusBadge status={member.approval_status} /> },
                { label: "Signs in to", value: "MBGA Delivery app" },
                { label: "Added on", value: formatDateTime(member.created_at) }
              ]}
            />
            <p className="meta" style={{ marginTop: "var(--space-4)" }}>
              Signs in with {formatMobileNumber(member.mobile_number)} using a verification code sent to that number.
            </p>
          </Card>
        </div>
      )}
      {status.dialog}
    </div>
  );
}
