/**
 * Mirrors backend `app/modules/authentication/mobile_number.py::normalize_mobile_number`.
 * Accepts a 10-digit Indian mobile number starting with 6-9, optionally prefixed with 91 / +91,
 * and returns "+91XXXXXXXXXX".
 * Returns null when the backend would reject the number, so invalid numbers are never sent
 * (the backend answers them with 422 INVALID_MOBILE_NUMBER).
 */
export function normalizeMobileNumber(input: string): string | null {
  const value = input.trim();
  if (!value || /[A-Za-z]/.test(value)) return null;
  let digits = value.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : null;
}

export function isValidMobileNumber(input: string): boolean {
  return normalizeMobileNumber(input) !== null;
}

/** "+919876543210" -> "+91 98765 43210" */
export function formatMobileNumber(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = normalizeMobileNumber(value);
  if (!normalized) return value;
  const local = normalized.slice(3);
  return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
}

/** "+919876543210" -> "+91 ••••• ••210" */
export function maskMobileNumber(value: string): string {
  const normalized = normalizeMobileNumber(value);
  if (!normalized) return value;
  const local = normalized.slice(3);
  return `+91 ••••• ••${local.slice(7)}`;
}

/** Local 10-digit part for display inside a "+91" prefixed input. */
export function localMobileDigits(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = normalizeMobileNumber(value);
  return normalized ? normalized.slice(3) : value;
}
