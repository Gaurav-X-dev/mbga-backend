import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it } from "vitest";

import { AppError, MESSAGES, isRetryableError, normalizeError } from "./errors";

const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;

function httpError(status: number, data: unknown, headers: Record<string, string> = {}) {
  const response = {
    status,
    statusText: "",
    data,
    headers: new AxiosHeaders(headers),
    config
  } as AxiosResponse;
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", config, {}, response);
}

describe("normalizeError", () => {
  it.each([
    ["NUMBER_NOT_REGISTERED", 404, "We could not find an active account for this mobile number."],
    ["OTP_INVALID", 400, "The verification code is incorrect. Please try again."],
    ["OTP_EXPIRED", 400, "This verification code has expired. Request a new code."],
    ["OTP_ATTEMPTS_EXCEEDED", 400, "Too many incorrect attempts. Request a new verification code."],
    ["ROLE_NOT_ASSIGNED", 403, "Your account does not have access to this panel."],
    ["ACCOUNT_BLOCKED", 403, "This account has been blocked. Please contact your administrator."]
  ])("maps login code %s to a safe message", (code, status, message) => {
    const error = normalizeError(httpError(status, { detail: { code, message: code.replace(/_/g, " ") } }));
    expect(error.userMessage).toBe(message);
    expect(error.code).toBe(code);
    expect(error.status).toBe(status);
  });

  it("keeps the backend code for debugging but never exposes backend text", () => {
    const error = normalizeError(httpError(400, { detail: { code: "SOMETHING_NEW", message: "Internal detail" } }));
    expect(error.userMessage).toBe(MESSAGES.validation);
    expect(error.userMessage).not.toContain("Internal");
    expect(error.debugMessage).toBe("Internal detail");
  });

  it("maps plain string details", () => {
    expect(normalizeError(httpError(403, { detail: "Permission denied" })).userMessage).toBe(MESSAGES.forbidden);
    expect(normalizeError(httpError(401, { detail: "Authentication required" })).kind).toBe("unauthorized");
    expect(normalizeError(httpError(404, { detail: "User not found" })).userMessage).toBe(MESSAGES.notFound);
    expect(normalizeError(httpError(400, { detail: "Super Admin role is protected" })).userMessage).toMatch(/protected/);
  });

  it("maps field conflicts onto form fields", () => {
    const error = normalizeError(httpError(409, { detail: { code: "MERCHANT_CODE_EXISTS", message: "exists" } }));
    expect(error.kind).toBe("conflict");
    expect(error.fieldErrors).toEqual({ merchant_code: "This merchant code is already in use. Choose a different code." });
  });

  it("maps FastAPI validation errors to field messages", () => {
    const error = normalizeError(
      httpError(422, {
        detail: [
          { type: "missing", loc: ["body", "business_name"], msg: "Field required" },
          { type: "string_too_short", loc: ["body", "merchant_code"], msg: "short", ctx: { min_length: 2 } },
          { type: "value_error", loc: ["body"], msg: "Value error, Driver requires driving license number and expiry" }
        ]
      })
    );
    expect(error.kind).toBe("validation");
    expect(error.fieldErrors).toEqual({
      business_name: "This field is required.",
      merchant_code: "Enter at least 2 characters.",
      driving_license_number: "Drivers need a driving licence number and expiry date."
    });
  });

  it("hides server errors and tracebacks", () => {
    const error = normalizeError(httpError(500, "Traceback (most recent call last): ValueError"));
    expect(error.kind).toBe("server");
    expect(error.userMessage).toBe(MESSAGES.server);
  });

  it("recognises network failures and timeouts", () => {
    expect(normalizeError(new AxiosError("Network Error", "ERR_NETWORK", config, {})).userMessage).toBe(MESSAGES.network);
    expect(normalizeError(new AxiosError("timeout", "ECONNABORTED", config, {})).kind).toBe("timeout");
  });

  it("keeps a request id when the server sends one", () => {
    const error = normalizeError(httpError(403, { detail: "Permission denied" }, { "x-request-id": "req-1" }));
    expect(error.requestId).toBe("req-1");
  });

  it("returns AppError instances unchanged and wraps unknown values", () => {
    const original = new AppError({ kind: "forbidden", userMessage: "x" });
    expect(normalizeError(original)).toBe(original);
    expect(normalizeError(new Error("boom")).userMessage).toBe(MESSAGES.unknown);
  });

  it("only retries transient failures", () => {
    expect(isRetryableError(httpError(503, {}))).toBe(true);
    expect(isRetryableError(new AxiosError("Network Error", "ERR_NETWORK", config, {}))).toBe(true);
    expect(isRetryableError(httpError(401, { detail: "Authentication required" }))).toBe(false);
    expect(isRetryableError(httpError(403, { detail: "Permission denied" }))).toBe(false);
    expect(isRetryableError(httpError(422, { detail: [] }))).toBe(false);
  });

  it("maps the coded validation envelope to field errors", () => {
    const error = normalizeError(
      httpError(422, {
        detail: {
          code: "VALIDATION_ERROR",
          message: "Some fields are missing or invalid.",
          fields: [{ field: "mobile_number", code: "missing", message: "Field required" }],
          request_id: "req-9"
        }
      })
    );
    expect(error.kind).toBe("validation");
    expect(error.fieldErrors).toEqual({ mobile_number: "This field is required." });
    expect(error.requestId).toBe("req-9");
  });

  it.each(["AUTH_REQUIRED", "TOKEN_EXPIRED", "TOKEN_INVALID", "TOKEN_CHANNEL_MISMATCH"])("treats %s as a signed-out session", (code) => {
    const error = normalizeError(httpError(401, { detail: { code, message: "x", fields: [] } }));
    expect(error.kind).toBe("unauthorized");
    expect(error.userMessage).toBe(MESSAGES.unauthorized);
  });

  it("shows a specific message for a blocked merchant", () => {
    const error = normalizeError(httpError(403, { detail: { code: "MERCHANT_BLOCKED", message: "x", fields: [] } }));
    expect(error.userMessage).toMatch(/business account is blocked/);
  });
});
