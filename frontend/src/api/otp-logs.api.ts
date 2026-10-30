import { apiClient } from "./client";
import { cleanParams } from "./params";

/**
 * Admin channel: GET /admin/auth/otp-logs. The response shape is not documented yet, so rows are
 * normalised here from either snake_case or camelCase, and the list from either an array or a
 * `{ items, total }` page.
 */
export type OtpLog = {
  id: string;
  requestId: string | null;
  /** Masked by the backend; the OTP code itself is never returned. */
  mobile: string | null;
  channel: string | null;
  purpose: string | null;
  status: string | null;
  /** The code, only while it is still usable (the backend nulls it once consumed or expired). */
  otp: string | null;
  maxAttempts: number | null;
  /** SENT, DELIVERED, FAILED… as the SMS provider reported it. */
  deliveryStatus: string | null;
  provider: string | null;
  consumed: boolean | null;
  attempts: number | null;
  ipAddress: string | null;
  device: string | null;
  createdAt: string | null;
  expiresAt: string | null;
  verifiedAt: string | null;
  failureReason: string | null;
  raw: Record<string, unknown>;
};

export type OtpLogPage = { items: OtpLog[]; total: number | null };

export type OtpLogParams = { limit: number; offset: number; search?: string; login_channel?: string; delivery_status?: string };

type Raw = Record<string, unknown>;

const pick = (row: Raw, ...keys: string[]) => {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return null;
};
const bool = (v: unknown) => (typeof v === "boolean" ? v : v === null || v === undefined ? null : ["true", "1", "yes"].includes(String(v).toLowerCase()));
const str = (v: unknown) => (v === null || v === undefined ? null : String(v));
const num = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)) ? Number(v) : null);

function deriveStatus(row: Raw) {
  const explicit = str(pick(row, "status", "state", "result"));
  if (explicit) {
    const value = explicit.toUpperCase();
    return value === "CONSUMED" || value === "USED" ? "VERIFIED" : value;
  }
  const verified = pick(row, "verified", "is_verified", "isVerified", "success");
  if (verified === true) return "VERIFIED";
  if (pick(row, "verified_at", "verifiedAt", "consumed_at", "consumedAt")) return "VERIFIED";
  if (bool(pick(row, "consumed", "is_consumed", "isConsumed"))) return "VERIFIED";
  const expires = str(pick(row, "expires_at", "expiresAt"));
  if (expires && new Date(expires).getTime() < Date.now()) return "EXPIRED";
  return verified === false ? "PENDING" : null;
}

function normalise(row: Raw, index: number): OtpLog {
  const mobile = str(pick(row, "masked_mobile", "maskedMobile", "mobile_masked", "mobileMasked", "mobile_number", "mobileNumber", "mobile", "phone"));
  const code = str(pick(row, "country_code", "countryCode"));
  return {
    id: str(pick(row, "id", "request_id", "requestId", "otp_request_id")) ?? `row-${index}`,
    requestId: str(pick(row, "request_id", "requestId", "otp_request_id", "otpRequestId", "id")),
    mobile: mobile && code && !mobile.startsWith("+") ? `${code} ${mobile}` : mobile,
    channel: str(pick(row, "login_channel", "loginChannel", "channel")),
    purpose: str(pick(row, "purpose", "type", "event", "action")),
    status: deriveStatus(row),
    otp: str(pick(row, "otp", "code")),
    maxAttempts: num(pick(row, "max_attempts", "maxAttempts")),
    deliveryStatus: str(pick(row, "delivery_status", "deliveryStatus", "sms_status", "smsStatus"))?.toUpperCase() ?? null,
    provider: str(pick(row, "provider", "delivery_provider", "deliveryProvider", "sms_provider", "smsProvider")),
    consumed: bool(pick(row, "consumed", "is_consumed", "isConsumed", "used", "is_used")) ?? (pick(row, "consumed_at", "consumedAt", "verified_at", "verifiedAt") ? true : null),
    attempts: num(pick(row, "attempts", "attempt_count", "attemptCount", "verify_attempts", "verifyAttempts")),
    ipAddress: str(pick(row, "ip_address", "ipAddress", "ip")),
    device: [str(pick(row, "device_name", "deviceName", "device_type", "deviceType", "user_agent", "userAgent")), str(pick(row, "app_version", "appVersion"))]
      .filter(Boolean)
      .join(" · v") || null,
    createdAt: str(pick(row, "created_at", "createdAt", "requested_at", "requestedAt", "sent_at", "sentAt")),
    expiresAt: str(pick(row, "expires_at", "expiresAt")),
    verifiedAt: str(pick(row, "consumed_at", "consumedAt", "verified_at", "verifiedAt")),
    failureReason: str(pick(row, "failure_reason", "failureReason", "delivery_reference", "deliveryReference", "error", "reason", "message")),
    raw: row
  };
}

export async function listOtpLogs(params: OtpLogParams, signal?: AbortSignal): Promise<OtpLogPage> {
  const { data } = await apiClient.get<unknown>("/admin/auth/otp-logs", { params: cleanParams(params), signal });
  const body = (data ?? {}) as Raw;
  const rows = (Array.isArray(data) ? data : Array.isArray(body.items) ? body.items : Array.isArray(body.data) ? body.data : []) as Raw[];
  const total = Array.isArray(data) ? null : num(body.total);
  return { items: rows.map(normalise), total };
}
