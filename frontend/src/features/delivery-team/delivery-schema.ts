import { z } from "zod";

import type {
  DeliveryMember,
  DeliveryMemberCreateInput,
  DeliveryMemberType,
  DeliveryMemberUpdateInput
} from "../../api/delivery-team.api";
import { mobileSchema, optionalEmailSchema, optionalText, requiredText } from "../../schemas/common";
import { emptyToNull, emptyToUndefined, todayInputValue, toDateInputValue } from "../../utils/format";
import { normalizeMobileNumber } from "../../utils/mobile";

/**
 * Mirrors backend DeliveryUserCreate (app/modules/delivery_users/schemas.py):
 * drivers need a licence number and an expiry date in the future.
 */
const memberFields = {
  full_name: requiredText("the full name", 2, 160),
  email: optionalEmailSchema,
  employee_code: requiredText("an employee code", 2, 80),
  driving_license_number: optionalText("licence number", 80),
  driving_license_expiry: z.string(),
  address: optionalText("address", 255)
};

function driverRules(values: { driving_license_number: string; driving_license_expiry: string }, ctx: z.RefinementCtx, isDriver: boolean) {
  if (!isDriver) return;
  if (!values.driving_license_number.trim()) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["driving_license_number"], message: "Enter the driving licence number." });
  }
  if (!values.driving_license_expiry) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["driving_license_expiry"], message: "Enter the licence expiry date." });
  } else if (values.driving_license_expiry <= todayInputValue()) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["driving_license_expiry"],
      message: "The licence has expired or expires today. Enter a future expiry date."
    });
  }
}

export const deliveryCreateSchema = z
  .object({
    delivery_user_type: z.enum(["DRIVER", "HELPER"], { errorMap: () => ({ message: "Choose driver or helper." }) }),
    mobile_number: mobileSchema,
    ...memberFields
  })
  .superRefine((values, ctx) => driverRules(values, ctx, values.delivery_user_type === "DRIVER"));

export type DeliveryCreateValues = z.infer<typeof deliveryCreateSchema>;

export function deliveryUpdateSchema(isDriver: boolean) {
  return z.object(memberFields).superRefine((values, ctx) => driverRules(values, ctx, isDriver));
}
export type DeliveryUpdateValues = z.infer<ReturnType<typeof deliveryUpdateSchema>>;

export const DELIVERY_FIELD_LABELS: Record<string, string> = {
  delivery_user_type: "Team member type",
  full_name: "Full name",
  mobile_number: "Mobile number",
  email: "Email address",
  employee_code: "Employee code",
  driving_license_number: "Driving licence number",
  driving_license_expiry: "Licence expiry date",
  address: "Address"
};

export const DELIVERY_CREATE_FIELDS = Object.keys(DELIVERY_FIELD_LABELS);

export function emptyDeliveryCreate(type: DeliveryMemberType | "" = ""): DeliveryCreateValues {
  return {
    delivery_user_type: type as DeliveryMemberType,
    full_name: "",
    mobile_number: "",
    email: "",
    employee_code: "",
    driving_license_number: "",
    driving_license_expiry: "",
    address: ""
  };
}

export function toDeliveryCreateInput(values: DeliveryCreateValues): DeliveryMemberCreateInput {
  const isDriver = values.delivery_user_type === "DRIVER";
  return {
    delivery_user_type: values.delivery_user_type,
    full_name: values.full_name.trim(),
    mobile_number: normalizeMobileNumber(values.mobile_number) ?? values.mobile_number,
    email: emptyToUndefined(values.email)?.toLowerCase(),
    employee_code: values.employee_code.trim(),
    // Licence details are only relevant for drivers.
    driving_license_number: isDriver ? emptyToUndefined(values.driving_license_number)?.toUpperCase() : undefined,
    driving_license_expiry: isDriver ? emptyToUndefined(values.driving_license_expiry) : undefined,
    address: emptyToUndefined(values.address)
  };
}

export function memberToUpdateValues(member: DeliveryMember): DeliveryUpdateValues {
  return {
    full_name: member.full_name ?? "",
    email: member.email ?? "",
    employee_code: member.employee_code ?? "",
    driving_license_number: member.driving_license_number ?? "",
    driving_license_expiry: toDateInputValue(member.driving_license_expiry),
    address: member.address ?? ""
  };
}

export function toDeliveryUpdateInput(values: DeliveryUpdateValues, original: DeliveryUpdateValues): DeliveryMemberUpdateInput {
  const input: DeliveryMemberUpdateInput = {};
  if (values.full_name.trim() !== original.full_name.trim()) input.full_name = values.full_name.trim();
  if (values.employee_code.trim() !== original.employee_code.trim()) input.employee_code = values.employee_code.trim();
  if (values.email.trim() !== original.email.trim()) input.email = emptyToNull(values.email)?.toLowerCase() ?? null;
  if (values.driving_license_number.trim() !== original.driving_license_number.trim()) {
    input.driving_license_number = emptyToNull(values.driving_license_number)?.toUpperCase() ?? null;
  }
  if (values.driving_license_expiry !== original.driving_license_expiry) {
    input.driving_license_expiry = emptyToNull(values.driving_license_expiry);
  }
  if (values.address.trim() !== original.address.trim()) input.address = emptyToNull(values.address);
  return input;
}
