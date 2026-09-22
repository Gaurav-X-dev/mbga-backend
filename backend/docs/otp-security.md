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
- `SMS_PROVIDER=hanuotp` delivers through HanuOTP and is the integrated production provider.
  See [HanuOTP delivery](#hanuotp-delivery) below.
- `SMS_PROVIDER=sms` is a generic vendor stub whose call is **not implemented**, so every send fails
  with `503 OTP_DELIVERY_FAILED` and nothing is stored. It is kept only so an additional vendor can be
  added later without changing the switch.
- The fixed development code (`DEV_FIXED_OTP_ENABLED`, `DEV_FIXED_OTP_CODE`) is accepted only in local,
  development and test environments and must have `OTP_LENGTH` digits. Its value must never appear in source,
  documentation or frontend configuration.


## HanuOTP delivery

One provider implementation serves **every** login channel — Customer, Customer registration,
Merchant, Delivery and Admin. All five resolve the same object through
`app.modules.authentication.dependencies.get_otp_provider`, so there is no per-app SMS client.

The backend generates and stores the code; HanuOTP only carries it. The provider never generates a
code, never changes an expiry and never touches a challenge.

### Configuration

| Variable | Meaning |
|---|---|
| `SMS_PROVIDER=hanuotp` | Selects the provider. One switch, no second configuration system. |
| `HANUOTP_BASE_URL` | Vendor endpoint. Must be `https`. |
| `HANUOTP_API_KEY` | Secret. Never defaulted, never committed, never logged. |
| `HANUOTP_TEMPLATE_ID` | DLT template id, currently `default`. |
| `HANUOTP_TIMEOUT_SECONDS` | Per-request timeout, default 10. |
| `HANUOTP_MAX_RETRIES` | Default **0** — see below. |
| `HANUOTP_LIVE_SMOKE_TEST_ENABLED` | Guards the one-off smoke script. Local/dev only. |
| `HANUOTP_SMOKE_TEST_MOBILE` | Destination for that single test message. |

Selecting `hanuotp` without the first three **fails at startup**, not at the first sign-in. A plain
`http://` base URL is refused, because the key and the code both travel as query parameters.

### Local, staging and production

- Local and test keep `SMS_PROVIDER=mock`: nothing is sent, and `DEV_FIXED_OTP_CODE` is used to sign in.
- `mock` is refused outside local/development/test, so a deployed environment cannot silently stop
  sending messages.
- Staging and production set `hanuotp` with a real key held in the environment, never in the repository.

### Retries

`HANUOTP_MAX_RETRIES` defaults to **0**. The vendor bills per message and the OTP flow already has its
own resend throttle, so a failed send is reported rather than silently retried into a second charge.
A vendor-declared rejection (bad key, no balance) is never retried at all; only timeouts and transport
failures are eligible when retries are deliberately enabled.

### Failure behaviour

The existing flow is unchanged: the challenge is created, delivery is attempted, and on failure the
transaction is rolled back and the caller receives the existing `503 OTP_DELIVERY_FAILED` with
`Retry-After: 30`. No challenge survives a failed send, so a failure cannot be verified against later.

A `2xx` response is **not** assumed to be a success. Several Indian gateways answer `200` with a
plain-text failure, so the body is inspected for an explicit verdict. A body that declares neither
success nor failure is treated as a failure — reporting a delivery we cannot see would leave the user
waiting for an SMS that never arrives, with no error and no retry.

### Log redaction

The request URL carries the API key *and* the code, so it is never logged, never attached to an
exception and never stored. Logs carry a masked number (`******8867`) and a short reason code such as
`HANUOTP_REJECTED`. Any vendor response that echoes the key, the code or the number is redacted before
it is stored as `delivery_reference` or printed by the smoke script.

### The one controlled smoke test

`scripts/smoke_test_hanuotp.py` sends exactly one real SMS to verify transport. It refuses to run
unless `HANUOTP_LIVE_SMOKE_TEST_ENABLED=true`, refuses outside local/development, requires the operator
to type `SEND`, makes one request with zero retries and exits. It prints only a masked destination, the
HTTP status, a sanitised body and a verdict.

Automated tests never reach the vendor: unit tests mock the HTTP transport and integration tests use a
capturing fake provider.

### Rotating or disabling the key

- **Rotate**: replace `HANUOTP_API_KEY` in the environment and restart. Nothing is cached and no stored
  data depends on the key.
- **Disable**: set `SMS_PROVIDER=sms` to fail every send loudly with `OTP_DELIVERY_FAILED`, or
  `SMS_PROVIDER=mock` in a local environment to stop sending entirely. There is no configuration in
  which HanuOTP is selected but silently skipped.

### Scope

This covers **OTP authentication SMS only**. Push notifications (FCM/APNs), order and payment alerts,
merchant dashboard alerts and general transactional SMS are not implemented by this integration.

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
