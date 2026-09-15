# Authentication Scaffold

## Source Requirements

The authentication scaffold is based on the MBGA SoW, Phase 1 SRS, and screen/field role spreadsheet.

- Customer, Driver/Helper, Merchant staff, and Admin-style users need role-aware access.
- Customer-facing login uses mobile number/OTP fields in the screen specification.
- Delivery app login is mobile number plus OTP for Driver and Helper.
- Merchant app login supports staff login identifier and password/OTP, so the scaffold keeps Admin and staff authentication separately configurable.
- API-layer RBAC is required; UI checks alone are not enough.

## OTP Request Flow

1. Client submits `mobile_number`, `country_code`, `login_channel`, and optional device data.
2. Mobile number is normalized.
3. Login channel is identified using `LoginChannel`.
4. User lookup and channel eligibility will be checked in the repository/service layer.
5. OTP is generated.
6. Only hashed OTP data is stored in Redis.
7. OTP delivery goes through an abstract provider.
8. Local development uses `MockOTPProvider`; real SMS integration is TODO.

The API must never return OTP values.

## OTP Verification Flow

Planned verification steps:

- Validate request ID.
- Validate OTP expiry.
- Enforce maximum attempts.
- Enforce one-time consumption.
- Prevent replay.
- Validate user status.
- Validate role against requested login channel.
- Create login session with device metadata.
- Issue access and refresh tokens.
- Write authentication audit event.

## Token Refresh Flow

Refresh token handling is scaffolded for:

- JWT expiry.
- Refresh token rotation.
- Session lookup.
- Revocation of the old refresh token.
- Audit logging.

## Logout Flow

The structure supports:

- Logout from current device/session.
- Logout from all devices.
- Refresh token/session revocation.

## Role And Channel Checks

`LoginChannel` values:

- `CUSTOMER`
- `DELIVERY`
- `MERCHANT`
- `ADMIN`

Channel access must be checked against database-assigned roles. Public OTP verification must never assign or upgrade a role.

OTP verification will call the RBAC effective-permission/login-channel service before issuing tokens. A user may authenticate only when at least one active assigned role is allowed for the requested `LoginChannel`; Admin-channel access is never inferred from a role name alone.

## Redis Key Strategy

Planned key names:

- `auth:otp:{request_id}` for hashed OTP metadata.
- `auth:otp:mobile-rate:{country_code}:{mobile_number}` for mobile request limits.
- `auth:otp:ip-rate:{ip}` for IP request limits.
- `auth:otp:cooldown:{country_code}:{mobile_number}:{login_channel}` for resend cooldown.
- `auth:session:{session_id}` for optional session metadata.
- `auth:revoked-refresh:{token_id}` for refresh token revocation checks.

## Required Environment Variables

See `.env.example` for application, MySQL, Redis, JWT, OTP, SMS, CORS, and trusted proxy settings.

## Security Precautions

- Do not store plain OTPs.
- Do not hard-code JWT secrets.
- Return generic responses where account existence must not be leaked.
- Confirm trusted proxy configuration before trusting forwarded IP headers.
- Keep Admin authentication separately configurable.
- Do not create users automatically unless MBGA explicitly confirms registration behavior.

## Current TODO Scope

- Real SMS provider integration.
- OTP attempt and cooldown metadata.
- Rate limiting.
- User lookup queries.
- Role/channel validation with persisted roles.
- Refresh token rotation and revocation persistence.
- Audit log persistence.
- Alembic migrations after model review.
# Authentication Status

Login and onboarding flows are intentionally postponed.

The product owner will separately finalize flows for:

- Super Admin/Admin
- Merchant
- Customer
- Delivery Partner
- Driver/Helper

Until then, no Admin password/JWT/refresh-token login endpoint is mounted. `/api/v1/admin/auth/*` must not appear in Swagger and must not be usable at runtime.

Current Admin/RBAC endpoints fail closed through `require_authenticated_user()`, which returns `401 Authentication required` until a verified current-user extraction mechanism is implemented. Automated tests may override this FastAPI dependency inside test code only; production code has no header backdoor or environment bypass.

Migration `20260914_0005` added generally useful user/security fields and session columns that may be reused after login is approved. Those fields are currently documented as reserved; they do not imply a finalized login flow.
