import axios from "axios";

export type AppErrorKind =
  | "network"
  | "timeout"
  | "cancelled"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "validation"
  | "conflict"
  | "rate_limited"
  | "server"
  | "unknown";

type AppErrorInit = {
  kind: AppErrorKind;
  userMessage: string;
  status?: number;
  code?: string;
  fieldErrors?: Record<string, string>;
  requestId?: string;
  debugMessage?: string;
};

/**
 * The only error shape screens deal with. `userMessage` is always safe to show;
 * `status`, `code` and `debugMessage` are kept for troubleshooting and are never rendered.
 */
export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly userMessage: string;
  readonly status?: number;
  readonly code?: string;
  readonly fieldErrors?: Record<string, string>;
  readonly requestId?: string;
  readonly debugMessage?: string;

  constructor(init: AppErrorInit) {
    super(init.userMessage);
    this.name = "AppError";
    this.kind = init.kind;
    this.userMessage = init.userMessage;
    this.status = init.status;
    this.code = init.code;
    this.fieldErrors = init.fieldErrors;
    this.requestId = init.requestId;
    this.debugMessage = init.debugMessage;
  }
}

export const MESSAGES = {
  network: "We could not connect to the server. Check your connection and try again.",
  timeout: "The server is taking too long to respond. Please try again.",
  server: "The service is temporarily unavailable. Please try again.",
  unauthorized: "Your session has ended. Please sign in again.",
  forbidden: "You don’t have permission to perform this action.",
  notFound: "We couldn’t find this record.",
  validation: "Please check the highlighted information.",
  conflict: "This information is already in use.",
  rateLimited: "Too many attempts. Please wait a moment and try again.",
  unknown: "Something went wrong. Please try again."
} as const;

/** Backend error codes (detail.code) mapped to safe, specific messages. */
const CODE_MESSAGES: Record<string, string> = {
  NUMBER_NOT_REGISTERED: "We could not find an active account for this mobile number.",
  OTP_INVALID: "The verification code is incorrect. Please try again.",
  OTP_EXPIRED: "This verification code has expired. Request a new code.",
  OTP_ATTEMPTS_EXCEEDED: "Too many incorrect attempts. Request a new verification code.",
  OTP_ALREADY_USED: "This verification code has already been used. Request a new code.",
  OTP_PURPOSE_MISMATCH: "This verification code is no longer valid. Request a new code.",
  OTP_RESEND_TOO_SOON: "Please wait a little before requesting another code.",
  OTP_RATE_LIMITED: "Too many verification codes were requested. Please wait a while and try again.",
  CHANNEL_NOT_ALLOWED: "Your account does not have access to this panel.",
  ROLE_NOT_ASSIGNED: "Your account does not have access to this panel.",
  PERMISSION_DENIED: "Your account does not have access to this panel.",
  ACCOUNT_BLOCKED: "This account has been blocked. Please contact your administrator.",
  ACCOUNT_INACTIVE: "This account is not active. Please contact your administrator.",
  ACCOUNT_PENDING_APPROVAL: "This account is not active yet. Please contact MBGA support.",
  SESSION_EXPIRED: "Your session has ended. Please sign in again.",
  SESSION_REVOKED: "Your session has ended. Please sign in again.",
  AUTH_REQUIRED: "Your session has ended. Please sign in again.",
  TOKEN_EXPIRED: "Your session has ended. Please sign in again.",
  TOKEN_INVALID: "Your session has ended. Please sign in again.",
  TOKEN_TYPE_NOT_ALLOWED: "Your session has ended. Please sign in again.",
  TOKEN_CHANNEL_MISMATCH: "Your session has ended. Please sign in again.",
  OTP_LOCKED: "Too many incorrect codes. Please wait a while and try again.",
  RATE_LIMITED: "Too many attempts. Please wait a moment and try again.",
  OTP_DELIVERY_FAILED: "We could not send the verification code. Please try again in a moment.",
  ACCOUNT_REJECTED: "This account was not approved. Please contact MBGA support.",
  ACCOUNT_SUSPENDED: "This account is suspended. Please contact MBGA support.",
  MERCHANT_BLOCKED: "Your business account is blocked. Please contact MBGA support.",
  MERCHANT_INACTIVE: "Your business account is not active. Please contact MBGA support.",
  MERCHANT_SCOPE_REQUIRED: "Your business account is not active. Please contact MBGA support.",
  MERCHANT_CODE_EXISTS: "This merchant code is already in use. Choose a different code.",
  MERCHANT_MOBILE_EXISTS: "A merchant with this mobile number already exists.",
  MOBILE_ALREADY_BLOCKED: "This mobile number belongs to a blocked account.",
  EMAIL_ALREADY_EXISTS: "This email address is already in use.",
  INVALID_MOBILE_NUMBER: "Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.",
  EMPLOYEE_CODE_EXISTS: "This employee code is already used in your team.",
  DELIVERY_MOBILE_EXISTS: "This mobile number is already registered to a delivery team member.",
  MERCHANT_USER_EXISTS: "This person is already a staff member of this merchant.",
  MERCHANT_NOT_FOUND: "We couldn’t find this merchant.",
  MERCHANT_USER_NOT_FOUND: "We couldn’t find this staff member.",
  DELIVERY_USER_NOT_FOUND: "We couldn’t find this team member.",
  ROLE_NOT_SEEDED: MESSAGES.server
};

const UNAUTHORIZED_CODES = new Set([
  "SESSION_EXPIRED",
  "SESSION_REVOKED",
  "AUTH_REQUIRED",
  "TOKEN_EXPIRED",
  "TOKEN_INVALID",
  "TOKEN_TYPE_NOT_ALLOWED",
  "TOKEN_CHANNEL_MISMATCH"
]);
const RATE_LIMIT_CODES = new Set(["OTP_RATE_LIMITED", "OTP_RESEND_TOO_SOON", "OTP_LOCKED", "RATE_LIMITED"]);

type CodedFieldError = { field?: string | null; code?: string; message?: string };

/** Which form field a backend error code belongs to. */
const CODE_FIELDS: Record<string, string> = {
  MERCHANT_CODE_EXISTS: "merchant_code",
  MERCHANT_MOBILE_EXISTS: "mobile_number",
  MOBILE_ALREADY_BLOCKED: "mobile_number",
  EMAIL_ALREADY_EXISTS: "email",
  INVALID_MOBILE_NUMBER: "mobile_number",
  EMPLOYEE_CODE_EXISTS: "employee_code",
  DELIVERY_MOBILE_EXISTS: "mobile_number",
  MERCHANT_USER_EXISTS: "mobile_number"
};

/** Plain-string `detail` values raised by the backend, matched case-insensitively. */
const TEXT_MESSAGES: Array<[RegExp, string]> = [
  [/authentication required/i, MESSAGES.unauthorized],
  [/permission denied/i, MESSAGES.forbidden],
  [/login is not allowed/i, "Your account does not have access to this panel."],
  [/super admin .*protected|protected.*super admin/i, "The Super Admin role is protected and cannot be changed this way."],
  [/system role is protected/i, "Built-in roles cannot be deleted."],
  [/last active super admin/i, "At least one active Super Admin is required."],
  [/role code already exists/i, "A role with this code already exists."],
  [/inactive role cannot be assigned/i, "This role is inactive. Activate it before assigning it."],
  [/role assignment already exists/i, "This user already has this role."],
  [/user already exists/i, "A user with this email or username already exists."],
  [/email, username or mobile number required/i, "Enter a mobile number or email address."],
  [/not found/i, MESSAGES.notFound]
];

/** Known model-level validation messages (Pydantic value errors). */
const VALUE_ERROR_MESSAGES: Array<[RegExp, string, string | undefined]> = [
  [/driver requires driving license/i, "Drivers need a driving licence number and expiry date.", "driving_license_number"],
  [/driving license expiry must be in the future/i, "The driving licence expiry date must be in the future.", "driving_license_expiry"],
  [/valid_until must be after valid_from/i, "The end date must be after the start date.", "valid_until"]
];

type PydanticIssue = {
  type?: string;
  loc?: Array<string | number>;
  msg?: string;
  ctx?: Record<string, unknown>;
};

function validationMessage(issue: PydanticIssue): string {
  const ctx = issue.ctx ?? {};
  switch (issue.type) {
    case "missing":
      return "This field is required.";
    case "string_too_short":
      return `Enter at least ${String(ctx.min_length ?? "the minimum number of")} characters.`;
    case "string_too_long":
      return `Enter no more than ${String(ctx.max_length ?? "the allowed number of")} characters.`;
    case "string_pattern_mismatch":
      return "Check the format of this value.";
    case "date_from_datetime_parsing":
    case "date_parsing":
    case "datetime_parsing":
    case "datetime_from_date_parsing":
      return "Enter a valid date.";
    case "enum":
    case "literal_error":
      return "Choose one of the available options.";
    case "bool_parsing":
    case "int_parsing":
      return "Enter a valid value.";
    default:
      break;
  }
  if (issue.msg && /email/i.test(issue.msg)) return "Enter a valid email address.";
  return "Check this value.";
}

function mapValidationIssues(issues: PydanticIssue[]): { fieldErrors: Record<string, string>; formMessage?: string } {
  const fieldErrors: Record<string, string> = {};
  let formMessage: string | undefined;
  for (const issue of issues) {
    const path = (issue.loc ?? []).filter((part) => part !== "body" && part !== "query" && part !== "path");
    const known = VALUE_ERROR_MESSAGES.find(([pattern]) => pattern.test(issue.msg ?? ""));
    if (known) {
      const [, message, field] = known;
      if (field && path.length === 0) {
        fieldErrors[field] ??= message;
      } else if (path.length > 0) {
        fieldErrors[String(path[path.length - 1])] ??= message;
      } else {
        formMessage ??= message;
      }
      continue;
    }
    if (path.length === 0) {
      formMessage ??= MESSAGES.validation;
      continue;
    }
    const field = String(path[path.length - 1]);
    fieldErrors[field] ??= validationMessage(issue);
  }
  return { fieldErrors, formMessage };
}

function kindForStatus(status: number): AppErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422 || status === 400) return "validation";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "unknown";
}

function defaultMessage(kind: AppErrorKind): string {
  switch (kind) {
    case "network":
      return MESSAGES.network;
    case "timeout":
      return MESSAGES.timeout;
    case "unauthorized":
      return MESSAGES.unauthorized;
    case "forbidden":
      return MESSAGES.forbidden;
    case "not_found":
      return MESSAGES.notFound;
    case "validation":
      return MESSAGES.validation;
    case "conflict":
      return MESSAGES.conflict;
    case "rate_limited":
      return MESSAGES.rateLimited;
    case "server":
      return MESSAGES.server;
    default:
      return MESSAGES.unknown;
  }
}

/** Converts anything thrown by the HTTP layer into an AppError. Never leaks backend text. */
export function normalizeError(error: unknown): AppError {
  if (error instanceof AppError) return error;

  if (axios.isCancel(error)) {
    return new AppError({ kind: "cancelled", userMessage: "The request was cancelled." });
  }

  if (axios.isAxiosError(error)) {
    if (!error.response) {
      const timedOut = error.code === "ECONNABORTED" || error.code === "ETIMEDOUT";
      return new AppError({
        kind: timedOut ? "timeout" : "network",
        userMessage: timedOut ? MESSAGES.timeout : MESSAGES.network,
        code: error.code,
        debugMessage: error.message
      });
    }

    const { status, data, headers } = error.response;
    const detail = (data as { detail?: unknown } | undefined)?.detail;
    const requestId =
      (headers?.["x-request-id"] as string | undefined) ??
      (detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as { request_id?: string }).request_id : undefined) ??
      undefined;
    let kind = kindForStatus(status);

    if (status >= 500) {
      const code =
        detail && typeof detail === "object" && !Array.isArray(detail)
          ? (detail as { code?: string }).code
          : undefined;
      return new AppError({ kind: "server", userMessage: MESSAGES.server, status, code, requestId });
    }

    if (Array.isArray(detail)) {
      const { fieldErrors, formMessage } = mapValidationIssues(detail as PydanticIssue[]);
      return new AppError({
        kind: "validation",
        status,
        userMessage: formMessage ?? MESSAGES.validation,
        fieldErrors: Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined,
        requestId,
        debugMessage: JSON.stringify(detail)
      });
    }

    if (detail && typeof detail === "object") {
      const { code, message, fields } = detail as { code?: string; message?: string; fields?: CodedFieldError[] };
      if (code === "VALIDATION_ERROR" && Array.isArray(fields) && fields.length > 0) {
        const { fieldErrors, formMessage } = mapValidationIssues(
          fields.map((item) => ({ type: item.code, loc: item.field ? item.field.split(".") : [], msg: item.message }))
        );
        return new AppError({
          kind: "validation",
          status,
          code,
          userMessage: formMessage ?? MESSAGES.validation,
          fieldErrors: Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined,
          requestId,
          debugMessage: message
        });
      }
      const field = code ? CODE_FIELDS[code] : undefined;
      const userMessage = (code && CODE_MESSAGES[code]) ?? defaultMessage(kind);
      if (field) kind = "conflict";
      if (code && UNAUTHORIZED_CODES.has(code)) kind = "unauthorized";
      if (code && RATE_LIMIT_CODES.has(code)) kind = "rate_limited";
      return new AppError({
        kind: code === "INVALID_MOBILE_NUMBER" ? "validation" : kind,
        status,
        code,
        userMessage,
        fieldErrors: field ? { [field]: userMessage } : undefined,
        requestId,
        debugMessage: message
      });
    }

    if (typeof detail === "string") {
      const match = TEXT_MESSAGES.find(([pattern]) => pattern.test(detail));
      return new AppError({
        kind,
        status,
        userMessage: match ? match[1] : defaultMessage(kind),
        requestId,
        debugMessage: detail
      });
    }

    return new AppError({ kind, status, userMessage: defaultMessage(kind), requestId });
  }

  return new AppError({
    kind: "unknown",
    userMessage: MESSAGES.unknown,
    debugMessage: error instanceof Error ? error.message : undefined
  });
}

export function getErrorMessage(error: unknown): string {
  return normalizeError(error).userMessage;
}

/** Validation, authentication and permission failures must never be retried automatically. */
export function isRetryableError(error: unknown): boolean {
  const appError = normalizeError(error);
  return appError.kind === "network" || appError.kind === "timeout" || appError.kind === "server";
}
