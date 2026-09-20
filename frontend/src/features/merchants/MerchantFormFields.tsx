import type { ReactNode } from "react";
import type { FieldErrors, UseFormRegister } from "react-hook-form";

import { Field, Input, PhoneInput } from "../../components/forms/Field";
import { fieldError } from "../../components/forms/form-utils";
import type { MerchantCreateValues } from "./merchant-schema";

type Props = {
  register: UseFormRegister<MerchantCreateValues>;
  errors: FieldErrors;
  /** Merchant code and mobile number cannot be changed after creation. */
  mode: "create" | "edit";
  disabled?: boolean;
};

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="form-section" aria-labelledby={`section-${title}`}>
      <div className="form-section__header">
        <h2 id={`section-${title}`} className="section-title">
          {title}
        </h2>
        <p className="text-muted text-small">{description}</p>
      </div>
      <div className="form-grid">{children}</div>
    </section>
  );
}

export function MerchantFormFields({ register, errors, mode, disabled }: Props) {
  const e = (name: string) => fieldError(errors, name);
  return (
    <>
      <Section title="Business information" description="How this merchant is identified across MBGA.">
        <Field label="Business name" required error={e("business_name")} hint="Example: Sharma Gas Agency">
          <Input id="field-business_name" autoComplete="organization" disabled={disabled} {...register("business_name")} />
        </Field>
        {mode === "create" ? (
          <Field
            label="Merchant code"
            required
            error={e("merchant_code")}
            hint="A short unique code, for example SHARMA-GAS-01. It cannot be changed later."
          >
            <Input
              id="field-merchant_code"
              autoCapitalize="characters"
              style={{ textTransform: "uppercase" }}
              disabled={disabled}
              {...register("merchant_code")}
            />
          </Field>
        ) : null}
        <Field label="GST number" optional error={e("gst_number")} hint="15-character GSTIN, if registered.">
          <Input
            id="field-gst_number"
            autoCapitalize="characters"
            style={{ textTransform: "uppercase" }}
            disabled={disabled}
            {...register("gst_number")}
          />
        </Field>
      </Section>

      <Section
        title="Primary contact"
        description={
          mode === "create"
            ? "This person will manage the merchant account and signs in with this mobile number."
            : "The person MBGA contacts about this merchant."
        }
      >
        <Field label="Contact person name" required error={e("contact_person_name")} hint="Example: Rakesh Sharma">
          <Input id="field-contact_person_name" autoComplete="name" disabled={disabled} {...register("contact_person_name")} />
        </Field>
        {mode === "create" ? (
          <Field
            label="Mobile number"
            required
            error={e("mobile_number")}
            hint="10-digit number. Used to sign in to the Merchant panel."
          >
            <PhoneInput id="field-mobile_number" disabled={disabled} {...register("mobile_number")} />
          </Field>
        ) : null}
        <Field label="Email address" optional error={e("email")} hint="Example: accounts@sharmagas.in">
          <Input id="field-email" type="email" autoComplete="email" disabled={disabled} {...register("email")} />
        </Field>
      </Section>

      <Section title="Address" description="Where the business operates from.">
        <Field label="Address line 1" optional error={e("address_line_1")} className="span-2" hint="Building, street">
          <Input id="field-address_line_1" autoComplete="address-line1" disabled={disabled} {...register("address_line_1")} />
        </Field>
        <Field label="Address line 2" optional error={e("address_line_2")} className="span-2" hint="Area, landmark">
          <Input id="field-address_line_2" autoComplete="address-line2" disabled={disabled} {...register("address_line_2")} />
        </Field>
        <Field label="City" optional error={e("city")}>
          <Input id="field-city" autoComplete="address-level2" disabled={disabled} {...register("city")} />
        </Field>
        <Field label="State" optional error={e("state")}>
          <Input id="field-state" autoComplete="address-level1" disabled={disabled} {...register("state")} />
        </Field>
        <Field label="PIN code" optional error={e("postal_code")} hint="Example: 110001">
          <Input
            id="field-postal_code"
            inputMode="numeric"
            autoComplete="postal-code"
            disabled={disabled}
            {...register("postal_code")}
          />
        </Field>
      </Section>
    </>
  );
}
