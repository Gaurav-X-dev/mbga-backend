import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";

import { createDeliveryMember, type DeliveryMember, type DeliveryMemberType } from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { StatusBadge } from "../../components/common/StatusBadge";
import { useToast } from "../../components/feedback/toast-context";
import { RadioGroup } from "../../components/forms/Field";
import { applyServerErrors, fieldError, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary, UnsavedChangesGuard } from "../../components/forms/FormParts";
import { DetailsPanel, PageHeader } from "../../components/layout/Page";
import { deliveryTypeLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { DeliveryMemberFields } from "./DeliveryMemberFields";
import {
  DELIVERY_CREATE_FIELDS,
  DELIVERY_FIELD_LABELS,
  deliveryCreateSchema,
  emptyDeliveryCreate,
  toDeliveryCreateInput,
  type DeliveryCreateValues
} from "./delivery-schema";

const BREADCRUMBS = [
  { label: "Dashboard", to: "/merchant/dashboard" },
  { label: "Delivery team", to: "/merchant/delivery-team" },
  { label: "Add team member" }
];

const TYPE_OPTIONS = [
  { value: "DRIVER", label: "Driver", description: "Drives the delivery vehicle. Needs a valid driving licence." },
  { value: "HELPER", label: "Helper", description: "Helps with loading and delivering cylinders." }
];

function initialType(value: string | null): DeliveryMemberType | "" {
  return value === "DRIVER" || value === "HELPER" ? value : "";
}

export function DeliveryMemberCreatePage() {
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [created, setCreated] = useState<DeliveryMember | null>(null);
  const successRef = useRef<HTMLDivElement>(null);
  const startType = initialType(searchParams.get("type"));

  const { register, handleSubmit, formState, setError, control, watch, reset } = useForm<DeliveryCreateValues>({
    resolver: zodResolver(deliveryCreateSchema),
    defaultValues: emptyDeliveryCreate(startType),
    mode: "onTouched"
  });
  const type = watch("delivery_user_type");

  const mutation = useMutation({
    mutationFn: (values: DeliveryCreateValues) => createDeliveryMember(toDeliveryCreateInput(values)),
    onSuccess: (member) => {
      queryClient.setQueryData(queryKeys.deliveryTeam.detail(member.id), member);
      void queryClient.invalidateQueries({ queryKey: queryKeys.deliveryTeam.lists() });
      toast.success(`${member.full_name ?? "The team member"} has been added.`);
      setCreated(member);
    },
    onError: (error) => setFormMessage(applyServerErrors(error, setError, DELIVERY_CREATE_FIELDS))
  });

  useEffect(() => {
    if (created) {
      successRef.current?.focus();
      window.scrollTo(0, 0);
    }
  }, [created]);

  if (created) {
    const isDriver = created.delivery_user_type === "DRIVER";
    return (
      <div className="page">
        <PageHeader title="Team member added" breadcrumbs={BREADCRUMBS} />
        <div className="success-panel" ref={successRef} tabIndex={-1} role="status">
          <span className="success-panel__icon" aria-hidden="true">
            <Icon name="checkCircle" size={26} />
          </span>
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <h2 className="section-title">{created.full_name} has joined your delivery team</h2>
            <p className="text-muted">
              <strong>Next step:</strong> ask {created.full_name ?? "them"} to open the MBGA Delivery app and sign in with{" "}
              <strong className="nowrap">{formatMobileNumber(created.mobile_number)}</strong>. They will receive a
              verification code on that number.
            </p>
          </div>
          <DetailsPanel
            items={[
              { label: "Full name", value: created.full_name },
              { label: "Mobile number", value: formatMobileNumber(created.mobile_number) },
              { label: "Team member type", value: deliveryTypeLabel(created.delivery_user_type) },
              { label: "Employee code", value: created.employee_code },
              { label: "Account status", value: <StatusBadge status={created.status} /> },
              { label: "Driving licence", value: created.driving_license_number, hidden: !isDriver }
            ]}
          />
          <div className="row">
            <ButtonLink to={`/merchant/delivery-team/${created.id}`} variant="primary">
              View team member
            </ButtonLink>
            <Button
              variant="secondary"
              icon="plus"
              onClick={() => {
                reset(emptyDeliveryCreate(""));
                setFormMessage(null);
                setCreated(null);
              }}
            >
              Add another team member
            </Button>
            <ButtonLink to="/merchant/delivery-team" variant="ghost">
              Back to delivery team
            </ButtonLink>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <UnsavedChangesGuard when={formState.isDirty && !mutation.isPending} />
      <PageHeader
        title="Add team member"
        description="Add a driver or helper to your delivery team. Fields marked * are required."
        breadcrumbs={BREADCRUMBS}
      />
      <form
        className="stack-lg"
        noValidate
        onSubmit={handleSubmit(
          (values) => {
            setFormMessage(null);
            mutation.mutate(values);
          },
          () => setFormMessage(null)
        )}
      >
        {formState.submitCount > 0 && (Object.keys(formState.errors).length > 0 || formMessage) ? (
          <FormErrorSummary errors={formState.errors} labels={DELIVERY_FIELD_LABELS} message={formMessage} />
        ) : null}

        <section className="form-section" aria-labelledby="section-type">
          <h2 id="section-type" className="sr-only">
            Team member type
          </h2>
          <Controller
            control={control}
            name="delivery_user_type"
            render={({ field }) => (
              <div id="field-delivery_user_type" tabIndex={-1} ref={field.ref}>
                <RadioGroup
                  legend="Team member type"
                  name={field.name}
                  value={field.value}
                  onChange={(value) => field.onChange(value)}
                  options={TYPE_OPTIONS}
                  error={fieldError(formState.errors, "delivery_user_type")}
                  required
                  disabled={mutation.isPending}
                />
              </div>
            )}
          />
        </section>

        <DeliveryMemberFields
          register={register}
          errors={formState.errors}
          isDriver={type === "DRIVER"}
          mode="create"
          disabled={mutation.isPending}
        />

        <div className="form-actions form-actions--sticky">
          <ButtonLink to="/merchant/delivery-team" variant="secondary">
            Cancel
          </ButtonLink>
          <Button type="submit" variant="accent" loading={mutation.isPending} loadingText="Adding team member…">
            Add team member
          </Button>
        </div>
      </form>
    </div>
  );
}
