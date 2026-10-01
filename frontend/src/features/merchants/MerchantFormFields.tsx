import type { FieldErrors, UseFormRegister } from "react-hook-form";

import { Field, Input, PhoneInput } from "../../components/forms/Field";
import { FormSection } from "../../components/forms/FormSection";
import { fieldError } from "../../components/forms/form-utils";
import type { MerchantCreateValues, MerchantFormSection } from "./merchant-schema";

type Props = {
  register: UseFormRegister<MerchantCreateValues>;
  errors: FieldErrors;
  /** Merchant code and mobile number cannot be changed after creation. */
  mode: "create" | "edit";
  disabled?: boolean;
  /** Render only one section (wizard); all sections when omitted. */
  section?: MerchantFormSection;
};

export function MerchantFormFields({ register, errors, mode, disabled, section }: Props) {
  const e = (name: string) => fieldError(errors, name);
  const show = (name: MerchantFormSection) => !section || section === name;
  return (
    <>
      {show("business") ? (
        <FormSection title="Business information" icon="store" description="How this gas agency is identified across MBGA.">
          <Field label="Business name" required error={e("business_name")} hint="Registered trading name, e.g. Sharma Gas Agency">
            <Input
              id="field-business_name"
              autoComplete="organization"
              placeholder="Sharma Gas Agency"
              disabled={disabled}
              {...register("business_name")}
            />
          </Field>
          {mode === "create" ? (
            <Field
              label="Merchant code"
              required
              error={e("merchant_code")}
              hint="Short unique code. It cannot be changed later."
            >
              <Input
                id="field-merchant_code"
                autoCapitalize="characters"
                placeholder="SHARMA-GAS-01"
                style={{ textTransform: "uppercase" }}
                disabled={disabled}
                {...register("merchant_code")}
              />
            </Field>
          ) : null}
          <Field label="GST number" optional error={e("gst_number")} hint="15-character GSTIN, if the agency is registered.">
            <Input
              id="field-gst_number"
              autoCapitalize="characters"
              placeholder="09ABCDE1234F1Z5"
              style={{ textTransform: "uppercase" }}
              disabled={disabled}
              {...register("gst_number")}
            />
          </Field>
        </FormSection>
      ) : null}

      {show("contact") ? (
        <FormSection
          title="Owner & contact"
          icon="user"
          description={
            mode === "create"
              ? "This person manages the merchant account and signs in with this mobile number."
              : "The person MBGA contacts about this merchant."
          }
        >
          <Field label="Contact person name" required error={e("contact_person_name")} hint="Owner or authorised manager">
            <Input
              id="field-contact_person_name"
              autoComplete="name"
              placeholder="Rakesh Sharma"
              disabled={disabled}
              {...register("contact_person_name")}
            />
          </Field>
          {mode === "create" ? (
            <Field label="Mobile number" required error={e("mobile_number")} hint="10-digit number used to sign in to the Merchant panel.">
              <PhoneInput id="field-mobile_number" disabled={disabled} {...register("mobile_number")} />
            </Field>
          ) : null}
          <Field label="Email address" optional error={e("email")} hint="For invoices and account notices.">
            <Input
              id="field-email"
              type="email"
              autoComplete="email"
              placeholder="accounts@sharmagas.in"
              disabled={disabled}
              {...register("email")}
            />
          </Field>
        </FormSection>
      ) : null}

      {show("region") ? (
        <FormSection title="Operating region" icon="mapPin" description="Where the agency operates from and distributes cylinders.">
          <Field label="Address line 1" optional error={e("address_line_1")} className="span-2" hint="Building, street">
            <Input
              id="field-address_line_1"
              autoComplete="address-line1"
              placeholder="114/32 Swaroop Nagar"
              disabled={disabled}
              {...register("address_line_1")}
            />
          </Field>
          <Field label="Address line 2" optional error={e("address_line_2")} className="span-2" hint="Area, landmark">
            <Input
              id="field-address_line_2"
              autoComplete="address-line2"
              placeholder="Near Moti Jheel"
              disabled={disabled}
              {...register("address_line_2")}
            />
          </Field>
          <Field label="City" optional error={e("city")}>
            <Input id="field-city" autoComplete="address-level2" placeholder="Kanpur" disabled={disabled} {...register("city")} />
          </Field>
          <Field label="State" optional error={e("state")}>
            <Input id="field-state" autoComplete="address-level1" placeholder="Uttar Pradesh" disabled={disabled} {...register("state")} />
          </Field>
          <Field label="PIN code" optional error={e("postal_code")} hint="6 digits">
            <Input
              id="field-postal_code"
              inputMode="numeric"
              autoComplete="postal-code"
              placeholder="208002"
              disabled={disabled}
              {...register("postal_code")}
            />
          </Field>
        </FormSection>
      ) : null}
    </>
  );
}
