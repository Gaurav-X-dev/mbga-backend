import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { createMerchant, type Merchant } from "../../api/merchants.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { StatusBadge } from "../../components/common/StatusBadge";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { applyServerErrors, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary, UnsavedChangesGuard } from "../../components/forms/FormParts";
import { DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatMobileNumber, normalizeMobileNumber } from "../../utils/mobile";
import { MerchantFormFields } from "./MerchantFormFields";
import {
  MERCHANT_CREATE_FIELDS,
  MERCHANT_FIELD_LABELS,
  emptyMerchantCreate,
  formatAddress,
  merchantCreateSchema,
  toMerchantCreateInput,
  type MerchantCreateValues
} from "./merchant-schema";

type Step = "form" | "review" | "done";

const BREADCRUMBS = [
  { label: "Dashboard", to: "/admin/dashboard" },
  { label: "Merchants", to: "/admin/merchants" },
  { label: "Add merchant" }
];

export function MerchantCreatePage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [step, setStep] = useState<Step>("form");
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [created, setCreated] = useState<Merchant | null>(null);
  const headingRef = useRef<HTMLDivElement>(null);

  const form = useForm<MerchantCreateValues>({
    resolver: zodResolver(merchantCreateSchema),
    defaultValues: emptyMerchantCreate,
    mode: "onTouched"
  });
  const { register, handleSubmit, formState, setError, getValues, reset } = form;

  const mutation = useMutation({
    mutationFn: (values: MerchantCreateValues) => createMerchant(toMerchantCreateInput(values)),
    onSuccess: (merchant) => {
      queryClient.setQueryData(queryKeys.merchants.detail(merchant.id), merchant);
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      setCreated(merchant);
      setStep("done");
      toast.success(`${merchant.business_name} has been added.`);
    },
    onError: (error) => {
      const appError = normalizeError(error);
      const message = applyServerErrors(appError, setError, MERCHANT_CREATE_FIELDS);
      // Known backend gap: a duplicate merchant email is reported as a server error.
      setFormMessage(
        appError.kind === "server"
          ? "We couldn’t create the merchant. If this email address is already used by another merchant, use a different one and try again."
          : message
      );
      // Field problems must be fixed on the form, not on the review step.
      if (Object.keys(form.formState.errors).length > 0) setStep("form");
    }
  });

  useEffect(() => {
    headingRef.current?.focus();
    window.scrollTo(0, 0);
  }, [step]);

  const values = getValues();

  if (step === "done" && created) {
    return (
      <div className="page">
        <PageHeader title="Merchant added" breadcrumbs={BREADCRUMBS} documentTitle="Merchant added" />
        <div className="success-panel" ref={headingRef} tabIndex={-1} role="status">
          <span className="success-panel__icon" aria-hidden="true">
            <Icon name="checkCircle" size={26} />
          </span>
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <h2 className="section-title">{created.business_name} is ready to use MBGA</h2>
            <p className="text-muted">
              {created.contact_person_name ?? "The contact person"} can now sign in to the Merchant panel with{" "}
              <strong className="nowrap">{formatMobileNumber(created.mobile_number)}</strong> using a verification code
              sent to that number.
            </p>
          </div>
          <DetailsPanel
            items={[
              { label: "Business name", value: created.business_name },
              { label: "Merchant code", value: created.merchant_code },
              { label: "Contact person", value: created.contact_person_name },
              { label: "Mobile number", value: formatMobileNumber(created.mobile_number) },
              { label: "Email address", value: created.email },
              { label: "Account status", value: <StatusBadge status={created.status} /> },
              { label: "Address", value: formatAddress(created) }
            ]}
          />
          <div className="row">
            <ButtonLink to={`/admin/merchants/${created.id}`} variant="primary">
              View merchant
            </ButtonLink>
            <Button
              variant="secondary"
              icon="plus"
              onClick={() => {
                reset(emptyMerchantCreate);
                setCreated(null);
                setFormMessage(null);
                setStep("form");
              }}
            >
              Add another merchant
            </Button>
            <Link to="/admin/merchants" className="btn btn--ghost">
              Back to merchants
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const blockLeave = formState.isDirty && !mutation.isPending && step !== "done";

  return (
    <div className="page">
      <UnsavedChangesGuard when={blockLeave} />
      <PageHeader
        title={step === "review" ? "Review and create" : "Add merchant"}
        documentTitle="Add merchant"
        description={
          step === "review"
            ? "Check the details below. You can go back to make changes."
            : "Enter the merchant’s details. Fields marked * are required."
        }
        breadcrumbs={BREADCRUMBS}
        meta={
          <span className="meta" aria-live="polite">
            Step {step === "form" ? 1 : 2} of 2
          </span>
        }
      />

      <div ref={headingRef} tabIndex={-1} className="stack-lg" style={{ outline: "none" }}>
        {step === "form" ? (
          <form
            className="stack-lg"
            noValidate
            onSubmit={handleSubmit(
              () => {
                setFormMessage(null);
                setStep("review");
              },
              () => setFormMessage(null)
            )}
          >
            {formState.submitCount > 0 && (Object.keys(formState.errors).length > 0 || formMessage) ? (
              <FormErrorSummary errors={formState.errors} labels={MERCHANT_FIELD_LABELS} message={formMessage} />
            ) : null}
            <MerchantFormFields register={register} errors={formState.errors} mode="create" />
            <div className="form-actions form-actions--sticky">
              <ButtonLink to="/admin/merchants" variant="secondary">
                Cancel
              </ButtonLink>
              <Button type="submit" variant="primary">
                Continue to review
              </Button>
            </div>
          </form>
        ) : (
          <div className="stack-lg">
            {formMessage ? <Alert tone="error">{formMessage}</Alert> : null}
            <section className="form-section" aria-labelledby="review-heading">
              <h2 id="review-heading" className="section-title">
                Merchant details
              </h2>
              <div className="review-list">
                <div className="stack" style={{ gap: "var(--space-2)" }}>
                  <h3 className="text-small text-muted">Business information</h3>
                  <DetailsPanel
                    items={[
                      { label: "Business name", value: values.business_name },
                      { label: "Merchant code", value: values.merchant_code.toUpperCase() },
                      { label: "GST number", value: values.gst_number.toUpperCase() }
                    ]}
                  />
                </div>
                <div className="stack" style={{ gap: "var(--space-2)" }}>
                  <h3 className="text-small text-muted">Primary contact</h3>
                  <DetailsPanel
                    items={[
                      { label: "Contact person", value: values.contact_person_name },
                      {
                        label: "Mobile number",
                        value: formatMobileNumber(normalizeMobileNumber(values.mobile_number) ?? values.mobile_number)
                      },
                      { label: "Email address", value: values.email }
                    ]}
                  />
                </div>
                <div className="stack" style={{ gap: "var(--space-2)" }}>
                  <h3 className="text-small text-muted">Address</h3>
                  <DetailsPanel items={[{ label: "Address", value: formatAddress(values) }]} />
                </div>
              </div>
            </section>
            <Alert tone="info" title="Account access">
              The account will be active straight away. {values.contact_person_name || "The contact person"} will be able
              to sign in to the Merchant panel with this mobile number.
            </Alert>
            <div className="form-actions form-actions--sticky">
              <Button variant="secondary" icon="arrowLeft" onClick={() => setStep("form")} disabled={mutation.isPending}>
                Back to edit
              </Button>
              <Button
                variant="accent"
                onClick={() => mutation.mutate(getValues())}
                loading={mutation.isPending}
                loadingText="Creating merchant…"
              >
                Create merchant
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
