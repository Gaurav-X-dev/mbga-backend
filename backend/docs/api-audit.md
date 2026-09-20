# API Audit

Total route operations discovered: 98

## Counts By Channel

- ADMIN: 52
- CUSTOMER: 8
- CUSTOMER_REGISTRATION: 13
- DELIVERY: 7
- INTERNAL: 1
- MERCHANT: 17

## Counts By Client

- ADMIN_WEB: 52
- CUSTOMER_APP: 21
- DELIVERY_APP: 7
- INTERNAL: 1
- MERCHANT_WEB,MERCHANT_APP: 17

## Duplicate Method/Path Registrations

None found.

## Intentional Channel Routes

Admin, Merchant, Customer, Customer registration, and Delivery auth routes intentionally expose separate URLs while using the shared channel auth router and AuthenticationService.

## Harmful Duplicated Code

No copied OTP generation/hash/verify/token/logout logic was found across channel routers. Legacy `/api/v1/auth/*` placeholder routes have been unmounted.

## Partial Or Placeholder APIs

- GET /api/v1/customer/registration/fields: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/logout: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/logout-all: PARTIAL,UNTESTED
- GET /api/v1/customer/registration/me: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/otp/request: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/otp/resend: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/otp/verify: PARTIAL,UNTESTED
- GET /api/v1/customer/registration/profile: PARTIAL,UNTESTED
- PATCH /api/v1/customer/registration/profile: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/profile: PARTIAL,UNTESTED
- GET /api/v1/customer/registration/status: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/submit: PARTIAL,UNTESTED
- POST /api/v1/customer/registration/token/refresh: PARTIAL,UNTESTED

## Untested Or Not Fully Traced APIs

- GET /api/v1/customer/registration/fields
- POST /api/v1/customer/registration/logout
- POST /api/v1/customer/registration/logout-all
- GET /api/v1/customer/registration/me
- POST /api/v1/customer/registration/otp/request
- POST /api/v1/customer/registration/otp/resend
- POST /api/v1/customer/registration/otp/verify
- GET /api/v1/customer/registration/profile
- PATCH /api/v1/customer/registration/profile
- POST /api/v1/customer/registration/profile
- GET /api/v1/customer/registration/status
- POST /api/v1/customer/registration/submit
- POST /api/v1/customer/registration/token/refresh
- GET /health
