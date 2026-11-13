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
  CUSTOMER_ACCOUNT_REQUIRED: "Select the customer account you want to use.",
  CUSTOMER_TEAM_CONFLICT: "This person already has access to that scope, or is the primary owner. Edit the existing Team entry.",
  BRANCH_CANNOT_MANAGE_BRANCHES: "A child branch cannot create or manage branches. Use its owner account.",
  REGISTRATION_PROFILE_EXISTS: "A customer with this mobile number already exists. Open that account or link it as an existing branch.",
  CUSTOMER_BRAND_NOT_EMPTY: "Unlink all branches and revoke additional brand users before disabling this owner group.",
  CUSTOMER_ACCESS_CONFLICT: "This account link conflicts with an existing owner, branch or user. Refresh Owner & branches and review the existing links.",
  CUSTOMER_TYPE_NOT_FOUND: "Select an available customer type.",
  CUSTOMER_TYPE_INACTIVE: "This customer type is inactive. Select an active type.",
  CUSTOMER_DELETE_OWNER_LINKED: "This customer owns a branch group with linked branches. Unlink them under Owner & branches first, then delete the customer. Branch accounts will be preserved.",
  CUSTOMER_DELETE_OUTLET_LINKED: "This customer belongs to a brand. Unlink it under Brand, outlets & account users before deleting.",
  CUSTOMER_DELETE_BLOCKED: "This customer has business records that prevent permanent deletion. Unlink any brand connection first. Orders, invoices, payments and other transaction history must be preserved.",
  PRIORITY_INVALID: "Select a priority from the current merchant options.",
  PRIORITY_IN_USE: "This priority is used by existing customers or orders. Keep its code and edit its label or rank.",
  TRIP_UNLOAD_CONFIRMATION: "Confirm that all trip stock has been physically unloaded before resetting the load.",
  TRIP_CHANGED: "This trip changed. Refresh its details and review your action again.",
  TRIP_ASSIGNMENT_INVALID: "Choose confirmed, scheduled deliveries for one vehicle, driver and date.",
  TRIP_ASSIGNMENT_CHANGED: "A delivery assignment changed. Reset or cancel the draft and plan it again.",
  TRIP_STOPS_INVALID: "Select unique stops within the configured trip limit.",
  TRIP_SEQUENCE_INVALID: "Include every trip stop exactly once and valid fixed-stop IDs.",
  TRIP_SEQUENCE_CLOSED: "This trip’s sequence can no longer be changed.",
  TRIP_STOP_FIXED: "Completed or arrived stops cannot be moved or have their map pin changed.",
  TRIP_COUNTS_INVALID: "Enter an actual return count for every cylinder type, including zeros.",
  TRIP_COORDINATES_INVALID: "Choose valid trip stops for the coordinate update.",
  TRIP_LOAD_SHORT: "The actual vehicle load must cover all planned cylinder allocations.",
  TRIP_LOAD_LIMIT: "The load exceeds the configured cylinder-count ceiling.",
  TRIP_LOAD_LOCKED: "This delivery is on a loaded trip. Verify unloading and reset the unstarted trip before editing its allocation.",
  TRIP_EMPTY_STOCK_SHORT: "Opening empties exceed available depot stock.",
  TRIP_STOPS_OPEN: "Complete or explicitly fail every stop before submitting the vehicle return.",
  TRIP_STATE_INVALID: "This action is unavailable at the trip’s current stage. Refresh its details.",
  TRIP_DEPOT_REQUIRED: "Set dispatch and return coordinates in App Settings or enter them for this trip.",
  TRIP_ODOMETER_REQUIRED: "Enter the required vehicle odometer reading.",
  TRIP_ODOMETER_INVALID: "Return odometer must be at least the dispatch reading.",
  TRIP_DATE_INVALID: "Start the trip on its scheduled India business date. Reschedule overdue deliveries before re-planning.",
  TRIP_EXPORT_LIMIT: "Too many trips or delivery lines match. Shorten the period or filter by vehicle/trip.",
  TRIP_ADJUSTMENT_NEGATIVE: "These return corrections would make stock negative. Review the counts and inventory.",
  USE_TRIP_START: "Start this delivery through its complete trip so vehicle loading remains consistent.",
  VEHICLE_TRIP_OPEN: "Reconcile the vehicle’s previous trip before starting another dispatch.",
  VEHICLE_ALREADY_OUT: "The vehicle already has deliveries on the road. Complete them before loading another trip.",
  DRIVER_UNAVAILABLE: "Assign an active, approved driver before loading this trip.",
  VERIFY_DISCREPANCY_FIRST: "Record the office discrepancy before authorizing stock corrections.",
  DELIVERY_ALREADY_IN_TRIP: "One of these deliveries already belongs to a trip. Refresh your selection.",
  ROUTE_COORDINATES_REQUIRED: "Every stop needs a saved delivery pin. Use Edit map pin or keep manual sequencing.",
  ROUTE_PREVIEW_CLOSED: "Optimize before departure. Only remaining stops can be manually re-sequenced after starting.",
  REMINDER_SETTINGS_MISSING: "Reminder settings are not installed. Apply the latest backend migration.",
  REMINDER_OVERRIDE_DISABLED: "The platform does not allow merchant overrides for this reminder.",
  REMINDER_RESOLVED: "This follow-up has already been resolved. Refresh the list.",
  INVALID_SNOOZE: "Choose a snooze duration within the configured policy limit.",
  VISIT_CONFLICT: "This visit was already saved with different details. Refresh before recording another visit.",
  INVALID_VISIT_DATE: "Visit time cannot be in the future.",
  INVALID_REMINDER_POLICY: "Check the reminder configuration and selected recipients.",
  RECIPIENT_NOT_FOUND: "Choose active recipients belonging to the selected merchant.",
  REPORT_EXPORT_LIMIT: "More than 10,000 rows match. Narrow the report filters before exporting.",
  GROUP_CONFLICT: "A reporting group with this name already exists for this merchant.",
  GROUP_NOT_FOUND: "This reporting group is unavailable for the selected merchant.",
  CUSTOMER_REQUIRED: "Select a customer to view invoice or receipt details.",
  COMPETITOR_EXPORT_LIMIT: "More than 10,000 audit events match. Select a shorter date range and export again.",
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
