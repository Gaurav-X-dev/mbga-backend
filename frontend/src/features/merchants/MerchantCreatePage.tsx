import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm, type FieldErrors } from "react-hook-form";
import { Link } from "react-router-dom";

import { createMerchant, type Merchant } from "../../api/merchants.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge } from "../../components/common/StatusBadge";
import { Alert } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { applyServerErrors, zodResolver } from "../../components/forms/form-utils";
import { FormErrorSummary, UnsavedChangesGuard } from "../../components/forms/FormParts";
import { Stepper, type Step } from "../../components/forms/FormSection";
import { DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatMobileNumber, normalizeMobileNumber } from "../../utils/mobile";
import { MerchantFormFields } from "./MerchantFormFields";
import {
  MERCHANT_CREATE_FIELDS,
  MERCHANT_FIELD_LABELS,
  MERCHANT_SECTION_FIELDS,
  type MerchantFormSection,
  emptyMerchantCreate,
  formatAddress,
  merchantCreateSchema,
  toMerchantCreateInput,
  type MerchantCreateValues
} from "./merchant-schema";

type StepId = MerchantFormSection | "review";

const STEPS: Array<Step & { id: StepId }> = [
  { id: "business", title: "Business information", description: "Name, code and GSTIN", icon: "store" },
  { id: "contact", title: "Owner & contact", description: "Who manages the account", icon: "user" },
  { id: "region", title: "Operating region", description: "Address and service area", icon: "mapPin" },
  { id: "review", title: "Review & submit", description: "Access setup and confirmation", icon: "checkCircle" }
];

const FORM_STEPS: MerchantFormSection[] = ["business", "contact", "region"];

function stepOfField(name: string): MerchantFormSection | undefined {
  return FORM_STEPS.find((step) => (MERCHANT_SECTION_FIELDS[step] as string[]).includes(name));
}

export function MerchantCreatePage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [step, setStep] = useState<StepId>("business");
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [attempted, setAttempted] = useState(false);
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [created, setCreated] = useState<Merchant | null>(null);
  const headingRef = useRef<HTMLDivElement>(null);

  const form = useForm<MerchantCreateValues>({
    resolver: zodResolver(merchantCreateSchema),
    defaultValues: emptyMerchantCreate,
    mode: "onTouched"
  });
  const { register, formState, setError, getValues, reset, trigger } = form;

  const mutation = useMutation({
    mutationFn: (values: MerchantCreateValues) => createMerchant(toMerchantCreateInput(values)),
    onSuccess: (merchant) => {
      queryClient.setQueryData(queryKeys.merchants.detail(merchant.id), merchant);
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      setCreated(merchant);
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
      // Field problems are fixed on the step that owns the field, not on the review step.
      const firstField = Object.keys(form.formState.errors)
        .map(stepOfField)
        .find(Boolean);
      if (firstField) {
        setAttempted(true);
        setStep(firstField);
      }
    }
  });

  useEffect(() => {
    headingRef.current?.focus();
    window.scrollTo(0, 0);
  }, [step, created]);

  async function next() {
    if (step === "review") return;
    const ok = await trigger(MERCHANT_SECTION_FIELDS[step]);
    if (!ok) {
      setAttempted(true);
      return;
    }
    setAttempted(false);
    setFormMessage(null);
    setCompleted((value) => new Set(value).add(step));
    setStep(STEPS[STEPS.findIndex((item) => item.id === step) + 1].id);
  }

  function goTo(id: string) {
    setAttempted(false);
    setStep(id as StepId);
  }

  if (created) {
    return (
      <div className="page">
        <PageHeader title="Merchant added" documentTitle="Merchant added" />
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
                setCompleted(new Set());
                setStep("business");
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

  const blockLeave = formState.isDirty && !mutation.isPending;
  const values = getValues();
  const stepIndex = STEPS.findIndex((item) => item.id === step);
  const stepErrors: FieldErrors =
    step === "review"
      ? {}
      : (Object.fromEntries(
          Object.entries(formState.errors).filter(([name]) => (MERCHANT_SECTION_FIELDS[step] as string[]).includes(name))
        ) as FieldErrors);
  const editButton = (target: MerchantFormSection) => (
    <Button variant="link" size="sm" icon="edit" onClick={() => goTo(target)}>
      Edit
    </Button>
  );

  return (
    <div className="page">
      <UnsavedChangesGuard when={blockLeave} />
      <PageHeader
        title={step === "review" ? "Review and create" : "Add merchant"}
        documentTitle="Add merchant"
        eyebrow="Merchant Network"
        description={
          step === "review"
            ? "Check the details below. You can go back to any step to make changes."
            : "Onboard a new gas agency partner. Fields marked * are required."
        }
        meta={
          <span className="meta" aria-live="polite">
            Step {stepIndex + 1} of {STEPS.length} · {STEPS[stepIndex].title}
          </span>
        }
      />

      <div className="wizard">
        <aside className="wizard__aside">
          <div className="wizard__progress" aria-hidden="true">
            <span style={{ width: `${((stepIndex + 1) / STEPS.length) * 100}%` }} />
          </div>
          <Stepper steps={STEPS} current={step} completed={completed} onSelect={goTo} />
        </aside>

        <div ref={headingRef} tabIndex={-1} className="wizard__main" style={{ outline: "none" }}>
          {step !== "review" ? (
            <form
              className="stack-lg"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void next();
              }}
            >
              {attempted && (Object.keys(stepErrors).length > 0 || formMessage) ? (
                <FormErrorSummary errors={stepErrors} labels={MERCHANT_FIELD_LABELS} message={formMessage} />
              ) : null}
              <MerchantFormFields register={register} errors={formState.errors} mode="create" section={step} />
              <div className="form-actions form-actions--sticky">
                {stepIndex > 0 ? (
                  <Button variant="ghost" icon="arrowLeft" onClick={() => goTo(STEPS[stepIndex - 1].id)}>
                    Back
                  </Button>
                ) : null}
                <span className="form-actions__spacer" />
                <ButtonLink to="/admin/merchants" variant="secondary">
                  Cancel
                </ButtonLink>
                <Button type="submit" variant="primary">
                  {step === "region" ? "Continue to review" : "Continue"}
                </Button>
              </div>
            </form>
          ) : (
            <div className="stack-lg">
              {formMessage ? <Alert tone="error">{formMessage}</Alert> : null}
              <section className="form-section" aria-labelledby="review-heading">
                <div className="form-section__header">
                  <span className="form-section__icon" aria-hidden="true">
                    <Icon name="checkCircle" size={18} />
                  </span>
                  <div>
                    <h2 id="review-heading" className="card-title">
                      Merchant details
                    </h2>
                    <p className="card-subtitle">Everything below will be saved to the merchant record.</p>
                  </div>
                </div>
                <div className="review-list">
                  <div className="review-group">
                    <div className="review-group__header">
                      <h3>Business information</h3>
                      {editButton("business")}
                    </div>
                    <DetailsPanel
                      items={[
                        { label: "Business name", value: values.business_name },
                        { label: "Merchant code", value: values.merchant_code.toUpperCase() },
                        { label: "GST number", value: values.gst_number.toUpperCase() }
                      ]}
                    />
                  </div>
                  <div className="review-group">
                    <div className="review-group__header">
                      <h3>Owner & contact</h3>
                      {editButton("contact")}
                    </div>
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
                  <div className="review-group">
                    <div className="review-group__header">
                      <h3>Operating region</h3>
                      {editButton("region")}
                    </div>
                    <DetailsPanel items={[{ label: "Address", value: formatAddress(values) }]} columns={1} />
                  </div>
                  <div className="review-group">
                    <div className="review-group__header">
                      <h3>Access setup</h3>
                    </div>
                    <DetailsPanel
                      items={[
                        { label: "Account status", value: <StatusBadge status="ACTIVE" /> },
                        { label: "Sign-in channel", value: <Badge tone="info">Merchant panel</Badge> },
                        { label: "Sign-in method", value: "One-time code to the mobile number" },
                        { label: "Primary user", value: values.contact_person_name }
                      ]}
                    />
                  </div>
                </div>
              </section>
              <Alert tone="info" title="Account access">
                The account will be active straight away. {values.contact_person_name || "The contact person"} will be able
                to sign in to the Merchant panel with this mobile number.
              </Alert>
              <div className="form-actions form-actions--sticky">
                <Button variant="ghost" icon="arrowLeft" onClick={() => goTo("region")} disabled={mutation.isPending}>
                  Back
                </Button>
                <span className="form-actions__spacer" />
                <ButtonLink to="/admin/merchants" variant="secondary">
                  Cancel
                </ButtonLink>
                <Button
                  variant="primary"
                  icon="check"
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
    </div>
  );
}
