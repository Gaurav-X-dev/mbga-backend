# OTP and Session Security

## Codes

- Mobile numbers are normalized to `+91XXXXXXXXXX` before any lookup; only Indian mobile numbers are accepted.
- Codes are numeric strings of `OTP_LENGTH` digits (currently 4). The request schema and the service both use this setting.
- Each challenge is bound to a purpose (`{CHANNEL}_LOGIN` or `CUSTOMER_REGISTRATION`) and an app channel.
- Only a pbkdf2 hash of the code is stored. Codes are never returned, logged or written to audit records.
- A code expires after `OTP_EXPIRY_SECONDS` (300), allows `OTP_MAX_ATTEMPTS` (5) wrong entries and can be used once.
  A new request or a resend cancels earlier codes for the same number, purpose and channel.
- Resend is allowed after `OTP_RESEND_COOLDOWN_SECONDS`; 429 responses carry `Retry-After`.

## Enumeration and abuse limits

- `otp/request` returns the same 202 response for every valid number. Codes are sent only to accounts that may
  use the app; for other numbers a "suppressed" challenge is stored, nothing is sent and no code (including the
  development code) can verify it.
- Hourly limits, stored in the database so they apply across all backend instances:

| Limit | Setting | Default |
| --- | --- | --- |
| Codes per number, purpose and app | `OTP_MAX_REQUESTS_PER_HOUR` | 5 |
| Wrong codes per number, purpose and app (all codes) | `OTP_MAX_FAILED_ATTEMPTS_PER_HOUR` | 10 → `OTP_LOCKED` |
| Code requests per client IP | `OTP_REQUEST_LIMIT_PER_IP` | 20 |
| Code requests per device ID | `OTP_REQUEST_LIMIT_PER_DEVICE` | 10 |
| Code verifications per client IP | `OTP_VERIFY_LIMIT_PER_IP` | 60 |
| `check-mobile` calls per client IP | `CHECK_MOBILE_LIMIT_PER_IP` | 30 |

- The client IP is the TCP peer, or the first untrusted address in `X-Forwarded-For` when the peer is listed in
  `TRUSTED_PROXY_IPS`. Configure this for the production load balancer, or all users will share one IP.
- IPs, device IDs and numbers are stored in `auth_throttle_events` only as HMAC hashes. Rows older than one hour
  are no longer counted and can be purged (`RequestThrottle.purge_expired`).
- `check-mobile` still reveals whether a customer registration exists (required by the Customer app flow);
  it is limited per IP.

## Delivery

- `SMS_PROVIDER=mock` is accepted only in local, development and test environments and never sends or logs codes.
- `SMS_PROVIDER=sms` requires `SMS_API_BASE_URL`, `SMS_API_KEY` and `SMS_SENDER_ID`, applies
  `SMS_TIMEOUT_SECONDS` and retries retryable failures up to `SMS_MAX_RETRIES` times.
  **The vendor call itself is not implemented (blocked by SMS vendor selection)**, so every send currently
  fails with `503 OTP_DELIVERY_FAILED` and nothing is stored.
- The fixed development code (`DEV_FIXED_OTP_ENABLED`, `DEV_FIXED_OTP_CODE`) is accepted only in local,
  development and test environments and must have `OTP_LENGTH` digits. Its value must never appear in source,
  documentation or frontend configuration.

## Sessions and tokens

- Access tokens last 15 minutes; refresh tokens 30 days. Only a SHA-256 hash of the refresh token is stored.
- Every authenticated request checks the session row: it must exist, belong to the token's user, match the
  token's app channel and type, not be revoked or expired, and the account must still be allowed to use the app.
  Logout, logout-all, refresh, admin sign-out and account or merchant blocks therefore take effect immediately.
- Refresh rotates the session. All sessions created by rotating one sign-in share a `family_id`. Presenting an
  already-rotated refresh token more than `REFRESH_REUSE_GRACE_SECONDS` (10) after its rotation revokes the whole
  family (`REFRESH_TOKEN_REUSED`). Parallel refreshes inside the grace window are refused without revocation.
- Onboarding sessions (customer registration) are accepted only on `/customer/registration/*`.
- Push tokens are stored on the session and cleared when the session is revoked.

## Configuration guards (startup fails outside local/development/test)

- `JWT_SIGNING_SECRET` must not be a placeholder and must be a random value of at least 32 bytes.
  Settings validation errors never include the rejected value.
- `DEBUG=true`, `SMS_PROVIDER=mock` and `DEV_FIXED_OTP_ENABLED=true` are refused.
- Swagger UI and OpenAPI JSON are disabled unless `API_DOCS_ENABLED=true`.

## Audit

Authentication events are written to `audit_logs` with event types `auth.*` (code requested, resend, request
rejected, verification succeeded or failed, login succeeded or rejected, token refreshed or rejected, refresh
token reuse detected, logout, logout-all, blocked account access). Each record stores the app channel, result,
reason code, masked mobile number (`******1234`), SHA-256 of the device ID and, if `AUTH_AUDIT_STORE_IP=true`,
the client IP. Codes, tokens and full numbers are never stored.

## Response headers

All responses carry `X-Request-ID`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer` and a restrictive `Permissions-Policy`. API responses carry a restrictive
`Content-Security-Policy`; sign-in and onboarding responses carry `Cache-Control: no-store`. HSTS is added
outside local environments.
