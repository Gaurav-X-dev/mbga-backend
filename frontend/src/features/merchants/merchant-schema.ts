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
  postal_code: optionalText("PIN code", 20),
  /**
   * The agency's own VPA, and the name the customer's payment app shows before they confirm.
   * Checked here as well as on the server: a malformed address still renders a QR, and the
   * failure then surfaces on the customer's phone with the driver standing at the gate.
   *
   * The backend refuses one without the other, because half a configuration behaves exactly
   * like none - the driver app shows a QR only when both are set.
   */
  upi_id: requiredText("the UPI ID", 3, 120).refine(
    (value) => /^[a-zA-Z0-9][a-zA-Z0-9.\-_]{1,255}@[a-zA-Z][a-zA-Z0-9.\-]{1,63}$/.test(value.trim()),
    "A UPI ID looks like name@bank, for example madhavgas@okhdfcbank."
  ),
  upi_payee_name: requiredText("the UPI payee name", 2, 160),
  /**
   * The bank an invoice names for a NEFT transfer. Optional: an agency that takes no
   * transfers needs none of it, and an invoice without bank details is still valid.
   *
   * The IFSC is checked because a wrong one does not fail here - it fails days later when
   * the transfer bounces, by which time nobody connects it back to this screen.
   */
  invoice_bank_name: optionalText("bank name", 160),
  invoice_bank_account_name: optionalText("account holder name", 160),
  invoice_bank_account_number: optionalText("account number", 80).refine(
    (value) => !value || /^[A-Za-z0-9]{6,20}$/.test(value.replace(/\s/g, "")),
    "An account number is 6 to 20 letters or digits."
  ),
  invoice_bank_ifsc: optionalText("IFSC", 30).refine(
    (value) => !value || /^[A-Za-z]{4}0[A-Za-z0-9]{6}$/.test(value.trim()),
    "An IFSC looks like HDFC0001234 - four letters, a zero, then six characters."
  )
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
  postal_code: "PIN code",
  upi_id: "UPI ID",
  upi_payee_name: "UPI payee name",
  invoice_bank_name: "Bank name",
  invoice_bank_account_name: "Account holder name",
  invoice_bank_account_number: "Account number",
  invoice_bank_ifsc: "IFSC"
};

export const MERCHANT_CREATE_FIELDS = Object.keys(MERCHANT_FIELD_LABELS);

export type MerchantFormSection = "business" | "contact" | "region" | "payments";

/** Which fields each form section owns - the create wizard validates one section at a time. */
export const MERCHANT_SECTION_FIELDS: Record<MerchantFormSection, Array<keyof MerchantCreateValues>> = {
  business: ["business_name", "merchant_code", "gst_number"],
  contact: ["contact_person_name", "mobile_number", "email"],
  region: ["address_line_1", "address_line_2", "city", "state", "postal_code"],
  payments: [
    "upi_id",
    "upi_payee_name",
    "invoice_bank_name",
    "invoice_bank_account_name",
    "invoice_bank_account_number",
    "invoice_bank_ifsc"
  ]
};

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
  postal_code: "",
  upi_id: "",
  upi_payee_name: "",
  invoice_bank_name: "",
  invoice_bank_account_name: "",
  invoice_bank_account_number: "",
  invoice_bank_ifsc: ""
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
    postal_code: emptyToUndefined(values.postal_code),
    // Lowercased to match the server: UPI handles are not case-sensitive, so two spellings
    // of one address must not read as two different addresses.
    upi_id: values.upi_id.trim().toLowerCase(),
    upi_payee_name: values.upi_payee_name.trim(),
    invoice_bank_name: emptyToUndefined(values.invoice_bank_name),
    invoice_bank_account_name: emptyToUndefined(values.invoice_bank_account_name),
    invoice_bank_account_number: emptyToUndefined(values.invoice_bank_account_number)?.replace(/\s/g, ""),
    invoice_bank_ifsc: emptyToUndefined(values.invoice_bank_ifsc)?.toUpperCase()
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
    postal_code: merchant.postal_code ?? "",
    upi_id: merchant.upi_id ?? "",
    upi_payee_name: merchant.upi_payee_name ?? "",
    invoice_bank_name: merchant.invoice_bank_name ?? "",
    invoice_bank_account_name: merchant.invoice_bank_account_name ?? "",
    invoice_bank_account_number: merchant.invoice_bank_account_number ?? "",
    invoice_bank_ifsc: merchant.invoice_bank_ifsc ?? ""
  };
}

/** Sends only the fields that changed. */
export function toMerchantUpdateInput(values: MerchantUpdateValues, original: MerchantUpdateValues): MerchantUpdateInput {
  const input: MerchantUpdateInput = {};
  const required = ["business_name", "contact_person_name", "upi_id", "upi_payee_name"] as const;
  const optional = ["email", "gst_number", "address_line_1", "address_line_2", "city", "state", "postal_code", "invoice_bank_name", "invoice_bank_account_name", "invoice_bank_account_number", "invoice_bank_ifsc"] as const;
  for (const key of required) {
    if (values[key].trim() !== original[key].trim()) {
      input[key] = key === "upi_id" ? values[key].trim().toLowerCase() : values[key].trim();
    }
  }
  for (const key of optional) {
    if (values[key].trim() !== original[key].trim()) {
      let value = emptyToNull(values[key]);
      if (value && key === "email") value = value.toLowerCase();
      if (value && key === "gst_number") value = value.toUpperCase();
      if (value && key === "invoice_bank_ifsc") value = value.toUpperCase();
      if (value && key === "invoice_bank_account_number") value = value.replace(/\s/g, "");
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
