import { describe, expect, it } from "vitest";

import { mobileSchema } from "../schemas/common";
import { formatMobileNumber, isValidMobileNumber, maskMobileNumber, normalizeMobileNumber } from "./mobile";

describe("normalizeMobileNumber (mirrors backend normalize_mobile_number)", () => {
  it.each([
    ["9876543210", "+919876543210"],
    ["98765 43210", "+919876543210"],
    ["+91 98765-43210", "+919876543210"],
    ["919876543210", "+919876543210"],
    ["+919876543210", "+919876543210"],
    ["6000000001", "+916000000001"]
  ])("accepts %s", (input, expected) => {
    expect(normalizeMobileNumber(input)).toBe(expected);
  });

  it.each(["", "12345", "98765432", "+1 415 555 0100", "98765abc10", "0919876543210", "929876543210", "0000000001", "+910000000001", "5876543210"])(
    "rejects %s",
    (input) => {
      expect(normalizeMobileNumber(input)).toBeNull();
      expect(isValidMobileNumber(input)).toBe(false);
    }
  );

  it("formats and masks for display", () => {
    expect(formatMobileNumber("+919876543210")).toBe("+91 98765 43210");
    expect(maskMobileNumber("+919876543210")).toBe("+91 ••••• ••210");
    expect(formatMobileNumber(null)).toBe("");
  });
});

describe("mobileSchema", () => {
  it("gives a friendly message for empty and invalid numbers", () => {
    const empty = mobileSchema.safeParse("");
    expect(empty.success).toBe(false);
    expect(empty.error?.issues[0].message).toBe("Enter a mobile number.");

    const invalid = mobileSchema.safeParse("12345");
    expect(invalid.success).toBe(false);
    expect(invalid.error?.issues[0].message).toBe("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.");
  });

  it("accepts a valid number", () => {
    expect(mobileSchema.safeParse(" 9876543210 ").success).toBe(true);
  });
});
