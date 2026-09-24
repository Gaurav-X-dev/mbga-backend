import { z } from "zod";

import { isValidMobileNumber } from "../utils/mobile";

export const MOBILE_MESSAGE = "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.";

/** Matches backend normalize_mobile_number: 10 digits starting with 6-9, optionally prefixed with 91 / +91. */
export const mobileSchema = z
  .string()
  .trim()
  .min(1, "Enter a mobile number.")
  .refine(isValidMobileNumber, MOBILE_MESSAGE);

export function requiredText(label: string, min: number, max: number) {
  return z
    .string()
    .trim()
    .min(1, `Enter ${label}.`)
    .min(min, `${capitalize(label)} must be at least ${min} characters.`)
    .max(max, `${capitalize(label)} must be ${max} characters or fewer.`);
}

export function optionalText(label: string, max: number) {
  return z
    .string()
    .trim()
    .max(max, `${capitalize(label)} must be ${max} characters or fewer.`);
}

export const optionalEmailSchema = z
  .string()
  .trim()
  .max(255, "Email address must be 255 characters or fewer.")
  .refine((value) => value === "" || z.string().email().safeParse(value).success, "Enter a valid email address, like name@example.com.");

function capitalize(value: string) {
  const text = value.replace(/^(a|an|the) /i, "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
