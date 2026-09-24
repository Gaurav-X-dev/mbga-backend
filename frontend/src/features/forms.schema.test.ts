import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deliveryCreateSchema, emptyDeliveryCreate, toDeliveryCreateInput } from "./delivery-team/delivery-schema";
import {
  emptyMerchantCreate,
  merchantCreateSchema,
  toMerchantCreateInput,
  toMerchantUpdateInput
} from "./merchants/merchant-schema";

function issues(result: { success: boolean; error?: { issues: Array<{ path: Array<string | number>; message: string }> } }) {
  // First message per field wins, matching the form resolver.
  const found: Record<string, string> = {};
  for (const issue of result.error?.issues ?? []) found[issue.path.join(".")] ??= issue.message;
  return found;
}

describe("merchant form validation", () => {
  const valid = {
    ...emptyMerchantCreate,
    merchant_code: "sharma-gas-01",
    business_name: "Sharma Gas Agency",
    contact_person_name: "Rakesh Sharma",
    mobile_number: "98765 43210"
  };

  it("requires the fields the backend requires", () => {
    const result = merchantCreateSchema.safeParse(emptyMerchantCreate);
    expect(Object.keys(issues(result)).sort()).toEqual(
      ["business_name", "contact_person_name", "merchant_code", "mobile_number"].sort()
    );
  });

  it("applies backend length limits", () => {
    const result = merchantCreateSchema.safeParse({ ...valid, business_name: "A", gst_number: "X".repeat(31) });
    const found = issues(result);
    expect(found.business_name).toMatch(/at least 2/);
    expect(found.gst_number).toMatch(/30 characters/);
  });

  it("validates optional email only when provided", () => {
    expect(merchantCreateSchema.safeParse({ ...valid, email: "" }).success).toBe(true);
    expect(issues(merchantCreateSchema.safeParse({ ...valid, email: "not-an-email" })).email).toMatch(/valid email/);
  });

  it("builds the exact backend payload", () => {
    const parsed = merchantCreateSchema.parse({ ...valid, email: "Accounts@Sharma.IN ", gst_number: "07aaacr5055k1z5" });
    expect(toMerchantCreateInput(parsed)).toEqual({
      merchant_code: "SHARMA-GAS-01",
      business_name: "Sharma Gas Agency",
      contact_person_name: "Rakesh Sharma",
      mobile_number: "+919876543210",
      email: "accounts@sharma.in",
      gst_number: "07AAACR5055K1Z5",
      address_line_1: undefined,
      address_line_2: undefined,
      city: undefined,
      state: undefined,
      postal_code: undefined
    });
  });

  it("sends only changed fields on update and clears emptied ones", () => {
    const original = {
      business_name: "A Gas",
      contact_person_name: "Ravi",
      email: "a@b.in",
      gst_number: "",
      address_line_1: "",
      address_line_2: "",
      city: "Delhi",
      state: "",
      postal_code: ""
    };
    expect(toMerchantUpdateInput({ ...original, city: "", business_name: "B Gas" }, original)).toEqual({
      business_name: "B Gas",
      city: null
    });
  });
});

describe("delivery team member form validation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-16T10:00:00"));
  });
  afterEach(() => vi.useRealTimers());

  const base = {
    ...emptyDeliveryCreate(""),
    full_name: "Suresh Kumar",
    mobile_number: "9123456780",
    employee_code: "DRV-014"
  };

  it("requires a team member type", () => {
    expect(issues(deliveryCreateSchema.safeParse(base)).delivery_user_type).toBe("Choose driver or helper.");
  });

  it("requires licence details for drivers", () => {
    const found = issues(deliveryCreateSchema.safeParse({ ...base, delivery_user_type: "DRIVER" }));
    expect(found.driving_license_number).toBe("Enter the driving licence number.");
    expect(found.driving_license_expiry).toBe("Enter the licence expiry date.");
  });

  it("rejects a licence that is not valid in the future", () => {
    const found = issues(
      deliveryCreateSchema.safeParse({
        ...base,
        delivery_user_type: "DRIVER",
        driving_license_number: "DL-1",
        driving_license_expiry: "2026-09-16"
      })
    );
    expect(found.driving_license_expiry).toMatch(/future expiry date/);
  });

  it("does not require licence details for helpers and never sends them", () => {
    const parsed = deliveryCreateSchema.parse({
      ...base,
      delivery_user_type: "HELPER",
      driving_license_number: "leftover",
      driving_license_expiry: "2020-01-01"
    });
    const payload = toDeliveryCreateInput(parsed);
    expect(payload.driving_license_number).toBeUndefined();
    expect(payload.driving_license_expiry).toBeUndefined();
    expect(payload.mobile_number).toBe("+919123456780");
  });

  it("requires an employee code and a valid mobile number", () => {
    const found = issues(
      deliveryCreateSchema.safeParse({ ...base, delivery_user_type: "HELPER", employee_code: "", mobile_number: "123" })
    );
    expect(found.employee_code).toBe("Enter an employee code.");
    expect(found.mobile_number).toBe("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.");
  });

  it("builds a valid driver payload", () => {
    const parsed = deliveryCreateSchema.parse({
      ...base,
      delivery_user_type: "DRIVER",
      driving_license_number: "dl-0420110012345",
      driving_license_expiry: "2030-01-31"
    });
    expect(toDeliveryCreateInput(parsed)).toMatchObject({
      delivery_user_type: "DRIVER",
      driving_license_number: "DL-0420110012345",
      driving_license_expiry: "2030-01-31",
      employee_code: "DRV-014"
    });
  });
});
