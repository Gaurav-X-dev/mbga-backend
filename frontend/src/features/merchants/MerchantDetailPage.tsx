import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, type UseFormRegister } from "react-hook-form";
import { useParams } from "react-router-dom";

import { getMerchant, updateMerchant, type Merchant } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Menu } from "../../components/common/Menu";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Tabs } from "../../components/common/Tabs";
import { Alert, ErrorState, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { applyServerErrors, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary, UnsavedChangesGuard } from "../../components/forms/FormParts";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatDate, formatDateTime } from "../../utils/format";
import { channelLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { MerchantFormFields } from "./MerchantFormFields";
import { MerchantStaffSection } from "./MerchantStaffSection";
import {
  MERCHANT_FIELD_LABELS,
  merchantToUpdateValues,
  merchantUpdateSchema,
  toMerchantUpdateInput,
  type MerchantCreateValues,
  type MerchantUpdateValues
} from "./merchant-schema";
import { useMerchantStatusActions } from "./useMerchantStatus";

function MerchantEditForm({ merchant, onDone }: { merchant: Merchant; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const original = merchantToUpdateValues(merchant);
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const { register, handleSubmit, formState, setError } = useForm<MerchantUpdateValues>({
    resolver: zodResolver(merchantUpdateSchema),
    defaultValues: original,
    mode: "onTouched"
  });

  const mutation = useMutation({
    mutationFn: (values: MerchantUpdateValues) => updateMerchant(merchant.id, toMerchantUpdateInput(values, original)),
    onSuccess: (updated) => {
      // The update response does not include the primary user, so keep the cached value.
      queryClient.setQueryData<Merchant>(queryKeys.merchants.detail(merchant.id), (previous) => ({
        ...updated,
        primary_user_id: previous?.primary_user_id ?? updated.primary_user_id
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Merchant details saved.");
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
        if (Object.keys(toMerchantUpdateInput(values, original)).length === 0) {
          onDone();
          return;
        }
        mutation.mutate(values);
      })}
    >
      <UnsavedChangesGuard when={formState.isDirty && !mutation.isPending && !mutation.isSuccess} />
      {formState.submitCount > 0 && (Object.keys(formState.errors).length > 0 || formMessage) ? (
        <FormErrorSummary errors={formState.errors} labels={MERCHANT_FIELD_LABELS} message={formMessage} />
      ) : null}
      <Alert tone="info">The merchant code and sign-in mobile number cannot be changed.</Alert>
      <MerchantFormFields
        register={register as unknown as UseFormRegister<MerchantCreateValues>}
        errors={formState.errors}
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

export function MerchantDetailPage() {
  const { merchantId = "" } = useParams();
  const auth = useAuth();
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState("overview");
  const status = useMerchantStatusActions();

  const query = useQuery({
    queryKey: queryKeys.merchants.detail(merchantId),
    queryFn: ({ signal }) => getMerchant(merchantId, signal)
  });
  const merchant = query.data;

  const breadcrumbs = [
    { label: "Dashboard", to: "/admin/dashboard" },
    { label: "Merchants", to: "/admin/merchants" },
    { label: merchant?.business_name ?? "Merchant" }
  ];

  if (query.isLoading) {
    return (
      <div className="page">
        <PageHeader title="Merchant" breadcrumbs={breadcrumbs} />
        <Card>
          <LoadingSkeleton rows={4} label="Loading merchant" />
        </Card>
      </div>
    );
  }

  if (!merchant) {
    return (
      <div className="page">
        <PageHeader title="Merchant" breadcrumbs={breadcrumbs} />
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const canEdit = auth.can(PERMISSIONS.merchantsUpdate);
  const statusActions = status.actionsFor(merchant);

  const overview = (
    <div className="stack-lg">
      <Card title="Business information" headingLevel={2}>
        <DetailsPanel
          items={[
            { label: "Business name", value: merchant.business_name },
            { label: "Merchant code", value: merchant.merchant_code },
            { label: "GST number", value: merchant.gst_number }
          ]}
        />
      </Card>
      <Card title="Primary contact">
        <DetailsPanel
          items={[
            { label: "Contact person", value: merchant.contact_person_name },
            { label: "Mobile number", value: formatMobileNumber(merchant.mobile_number) },
            { label: "Email address", value: merchant.email }
          ]}
        />
      </Card>
      <Card title="Address">
        <DetailsPanel
          items={[
            { label: "Address", value: [merchant.address_line_1, merchant.address_line_2].filter(Boolean).join(", ") },
            { label: "City", value: merchant.city },
            { label: "State", value: merchant.state },
            { label: "PIN code", value: merchant.postal_code }
          ]}
        />
      </Card>
      <Card title="Account">
        <DetailsPanel
          items={[
            { label: "Account status", value: <StatusBadge status={merchant.status} /> },
            { label: "Approval", value: <StatusBadge status={merchant.approval_status} /> },
            { label: "Signs in to", value: channelLabel(merchant.allowed_channel) },
            { label: "Added on", value: formatDateTime(merchant.created_at) }
          ]}
        />
      </Card>
    </div>
  );

  return (
    <div className="page">
      <PageHeader
        title={
          <span className="row" style={{ flexWrap: "nowrap" }}>
            <UserAvatar name={merchant.business_name} size="lg" />
            <span>{merchant.business_name}</span>
          </span>
        }
        documentTitle={merchant.business_name}
        breadcrumbs={breadcrumbs}
        meta={
          <>
            <StatusBadge status={merchant.status} />
            <span className="meta">Code {merchant.merchant_code}</span>
            <span className="meta">Added {formatDate(merchant.created_at)}</span>
            <RefreshIndicator active={query.isFetching} />
          </>
        }
        actions={
          editing ? undefined : (
            <>
              {canEdit ? (
                <Button
                  variant="secondary"
                  icon="edit"
                  onClick={() => {
                    setTab("overview");
                    setEditing(true);
                  }}
                >
                  Edit details
                </Button>
              ) : null}
              {statusActions.some((action) => !action.hidden) ? (
                <Menu label="More account actions" actions={statusActions} />
              ) : null}
            </>
          )
        }
      />

      {merchant.status === "BLOCKED" ? (
        <Alert tone="warning" title="This merchant is blocked">
          The merchant and their staff cannot sign in until the account is unblocked.
        </Alert>
      ) : null}

      {editing ? (
        <MerchantEditForm merchant={merchant} onDone={() => setEditing(false)} />
      ) : (
        <Tabs
          label="Merchant sections"
          activeId={tab}
          onChange={setTab}
          tabs={[
            { id: "overview", label: "Overview", content: overview },
            ...(auth.can(PERMISSIONS.merchantUsersView)
              ? [{ id: "staff", label: "Staff accounts", content: <MerchantStaffSection merchant={merchant} /> }]
              : [])
          ]}
        />
      )}
      {status.dialog}
    </div>
  );
}
