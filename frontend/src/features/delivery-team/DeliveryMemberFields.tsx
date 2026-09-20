import type { ReactNode } from "react";
import type { FieldErrors, UseFormRegister } from "react-hook-form";

import { Field, Input, PhoneInput, Textarea } from "../../components/forms/Field";
import { fieldError } from "../../components/forms/form-utils";
import { todayInputValue } from "../../utils/format";
import type { DeliveryCreateValues } from "./delivery-schema";

function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section className="form-section" aria-labelledby={id}>
      <div className="form-section__header">
        <h2 id={id} className="section-title">
          {title}
        </h2>
        {description ? <p className="text-muted text-small">{description}</p> : null}
      </div>
      <div className="form-grid">{children}</div>
    </section>
  );
}

type Props = {
  register: UseFormRegister<DeliveryCreateValues>;
  errors: FieldErrors;
  isDriver: boolean;
  mode: "create" | "edit";
  disabled?: boolean;
};

export function DeliveryMemberFields({ register, errors, isDriver, mode, disabled }: Props) {
  const e = (name: string) => fieldError(errors, name);
  return (
    <>
      <Section
        id="section-personal"
        title="Personal details"
        description={mode === "create" ? "The mobile number is used to sign in to the MBGA Delivery app." : undefined}
      >
        <Field label="Full name" required error={e("full_name")} hint="As shown on their ID, e.g. Suresh Kumar">
          <Input id="field-full_name" autoComplete="name" disabled={disabled} {...register("full_name")} />
        </Field>
        {mode === "create" ? (
          <Field label="Mobile number" required error={e("mobile_number")} hint="10-digit number they will sign in with.">
            <PhoneInput id="field-mobile_number" disabled={disabled} {...register("mobile_number")} />
          </Field>
        ) : null}
        <Field label="Email address" optional error={e("email")}>
          <Input id="field-email" type="email" autoComplete="email" disabled={disabled} {...register("email")} />
        </Field>
        <Field label="Employee code" required error={e("employee_code")} hint="Your own staff reference, e.g. DRV-014. Must be unique in your team.">
          <Input id="field-employee_code" disabled={disabled} {...register("employee_code")} />
        </Field>
        <Field label="Address" optional error={e("address")} className="span-2">
          <Textarea id="field-address" rows={2} autoComplete="street-address" disabled={disabled} {...register("address")} />
        </Field>
      </Section>

      {isDriver ? (
        <Section id="section-licence" title="Driving licence" description="Required for drivers. The licence must still be valid.">
          <Field label="Driving licence number" required error={e("driving_license_number")} hint="Example: DL-0420110012345">
            <Input
              id="field-driving_license_number"
              autoCapitalize="characters"
              style={{ textTransform: "uppercase" }}
              disabled={disabled}
              {...register("driving_license_number")}
            />
          </Field>
          <Field label="Licence expiry date" required error={e("driving_license_expiry")}>
            <Input
              id="field-driving_license_expiry"
              type="date"
              min={todayInputValue()}
              disabled={disabled}
              {...register("driving_license_expiry")}
            />
          </Field>
        </Section>
      ) : null}
    </>
  );
}
