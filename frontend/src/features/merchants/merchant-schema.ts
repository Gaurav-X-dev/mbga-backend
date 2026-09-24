import { z } from "zod";

import type { Merchant, MerchantCreateInput, MerchantUpdateInput } from "../../api/merchants.api";
import { mobileSchema, optionalEmailSchema, optionalText, requiredText } from "../../schemas/common";
import { emptyToNull, emptyToUndefined } from "../../utils/format";
import { normalizeMobileNumber } from "../../utils/mobile";

/** Mirrors backend MerchantCreate / MerchantUpdate (app/modules/merchants/schemas.py). */
const businessFields = {
  business_name: requiredText("the business name", 2, 160),
  contact_person_name: requiredText("the contact person’s name", 2, 160),
  email: optionalEmailSchema,
  gst_number: optionalText("GST number", 30),
  address_line_1: optionalText("address line 1", 255),
  address_line_2: optionalText("address line 2", 255),
  city: optionalText("city", 120),
  state: optionalText("state", 120),
  postal_code: optionalText("PIN code", 20)
};

export const merchantCreateSchema = z.object({
  merchant_code: requiredText("a merchant code", 2, 80).regex(
    /^[A-Za-z0-9][A-Za-z0-9-_]*$/,
    "Use letters, numbers, hyphens or underscores only."
  ),
  mobile_number: mobileSchema,
  ...businessFields
});

export const merchantUpdateSchema = z.object(businessFields);

export type MerchantCreateValues = z.infer<typeof merchantCreateSchema>;
export type MerchantUpdateValues = z.infer<typeof merchantUpdateSchema>;

export const MERCHANT_FIELD_LABELS: Record<string, string> = {
  merchant_code: "Merchant code",
  business_name: "Business name",
  gst_number: "GST number",
  contact_person_name: "Contact person",
  mobile_number: "Mobile number",
  email: "Email address",
  address_line_1: "Address line 1",
  address_line_2: "Address line 2",
  city: "City",
  state: "State",
  postal_code: "PIN code"
};

export const MERCHANT_CREATE_FIELDS = Object.keys(MERCHANT_FIELD_LABELS);

export const emptyMerchantCreate: MerchantCreateValues = {
  merchant_code: "",
  business_name: "",
  gst_number: "",
  contact_person_name: "",
  mobile_number: "",
  email: "",
  address_line_1: "",
  address_line_2: "",
  city: "",
  state: "",
  postal_code: ""
};

export function toMerchantCreateInput(values: MerchantCreateValues): MerchantCreateInput {
  return {
    merchant_code: values.merchant_code.trim().toUpperCase(),
    business_name: values.business_name.trim(),
    contact_person_name: values.contact_person_name.trim(),
    mobile_number: normalizeMobileNumber(values.mobile_number) ?? values.mobile_number,
    email: emptyToUndefined(values.email)?.toLowerCase(),
    gst_number: emptyToUndefined(values.gst_number)?.toUpperCase(),
    address_line_1: emptyToUndefined(values.address_line_1),
    address_line_2: emptyToUndefined(values.address_line_2),
    city: emptyToUndefined(values.city),
    state: emptyToUndefined(values.state),
    postal_code: emptyToUndefined(values.postal_code)
  };
}

export function merchantToUpdateValues(merchant: Merchant): MerchantUpdateValues {
  return {
    business_name: merchant.business_name ?? "",
    contact_person_name: merchant.contact_person_name ?? "",
    email: merchant.email ?? "",
    gst_number: merchant.gst_number ?? "",
    address_line_1: merchant.address_line_1 ?? "",
    address_line_2: merchant.address_line_2 ?? "",
    city: merchant.city ?? "",
    state: merchant.state ?? "",
    postal_code: merchant.postal_code ?? ""
  };
}

/** Sends only the fields that changed. */
export function toMerchantUpdateInput(values: MerchantUpdateValues, original: MerchantUpdateValues): MerchantUpdateInput {
  const input: MerchantUpdateInput = {};
  const required = ["business_name", "contact_person_name"] as const;
  const optional = ["email", "gst_number", "address_line_1", "address_line_2", "city", "state", "postal_code"] as const;
  for (const key of required) {
    if (values[key].trim() !== original[key].trim()) input[key] = values[key].trim();
  }
  for (const key of optional) {
    if (values[key].trim() !== original[key].trim()) {
      let value = emptyToNull(values[key]);
      if (value && key === "email") value = value.toLowerCase();
      if (value && key === "gst_number") value = value.toUpperCase();
      input[key] = value;
    }
  }
  return input;
}

export function formatAddress(merchant: Pick<Merchant, "address_line_1" | "address_line_2" | "city" | "state" | "postal_code">) {
  const cityLine = [merchant.city, merchant.state].filter(Boolean).join(", ");
  return [merchant.address_line_1, merchant.address_line_2, [cityLine, merchant.postal_code].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");
}
