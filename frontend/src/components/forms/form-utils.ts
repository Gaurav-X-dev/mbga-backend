import type { FieldErrors, FieldValues, Path, Resolver, UseFormSetError } from "react-hook-form";
import type { z } from "zod";

import { normalizeError } from "../../api/errors";

/** Minimal Zod resolver for react-hook-form (avoids an extra dependency). */
export function zodResolver<TSchema extends z.ZodTypeAny>(schema: TSchema): Resolver<z.infer<TSchema>> {
  return async (values) => {
    const result = await schema.safeParseAsync(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: Record<string, { type: string; message: string }> = {};
    for (const issue of result.error.issues) {
      const path = issue.path.join(".");
      if (path && !errors[path]) {
        errors[path] = { type: issue.code, message: issue.message };
      }
    }
    return { values: {}, errors: errors as unknown as FieldErrors<z.infer<TSchema>> };
  };
}

/**
 * Puts backend field errors onto the form and returns the message to show at form level.
 * Only fields that exist in the form are marked; everything else is summarised.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly string[]
): string {
  const appError = normalizeError(error);
  let firstField = true;
  let unmatched = false;
  for (const [field, message] of Object.entries(appError.fieldErrors ?? {})) {
    if (fields.includes(field)) {
      setError(field as Path<T>, { type: "server", message }, { shouldFocus: firstField });
      firstField = false;
    } else {
      unmatched = true;
    }
  }
  if (!firstField && !unmatched) {
    return appError.kind === "conflict" ? appError.userMessage : "Please check the highlighted information.";
  }
  return appError.userMessage;
}

export function fieldError(errors: FieldErrors, name: string): string | undefined {
  const entry = errors[name];
  return entry && typeof entry.message === "string" ? entry.message : undefined;
}
