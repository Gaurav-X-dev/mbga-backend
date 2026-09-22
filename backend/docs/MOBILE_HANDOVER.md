# MBGA Customer and Merchant KYC Mobile Handover

Verdict: ready with documented limitations.

This handover covers Customer Registration and Merchant Customer/KYC review only. Pricing, Orders, Delivery, Inventory, Payments, Expenses, Reports, Notifications and Dashboards are outside this handover.

## Ready Today

- Customer self-registration using the existing onboarding OTP/session flow.
- Customer KYC document upload and signed document viewing.
- Merchant-created Retail and Industrial Customers.
- Merchant Customer list, detail and order-eligibility check.
- Merchant KYC application list/detail.
- Merchant approve/reject flow.
- Strict KYC approval validation for every Customer record.
- Orphan staged-upload cleanup command.

## Unchanged

- Existing Customer and Merchant login APIs.
- OTP request/resend/verify behavior.
- Access/refresh token shapes and session behavior.
- `/customer/auth/me`, refresh, logout and logout-all.
- Pending Customer full login still returns `ACCOUNT_PENDING_APPROVAL`.

## Customer Flow

1. `/customer/registration/otp/request`
2. `/customer/registration/otp/verify` -> onboarding tokens
3. `POST /customer/documents` for required files
4. `POST /customer/registration/profile`
5. `POST /customer/registration/submit`
6. `GET /customer/registration/status` while pending
7. Merchant approval
8. Existing `/customer/auth/otp/request` and `/customer/auth/otp/verify`
9. `GET /customer/profile` for approved business profile

## Merchant Flow

1. Existing Merchant login.
2. Optional `POST /merchant/documents` for staff-created Customer documents.
3. `POST /merchant/customers`.
4. `GET /merchant/kyc/applications`.
5. `GET /merchant/kyc/applications/{application_id}`.
6. `GET /merchant/documents/{file_id}/url`, then content URL if needed.
7. `POST /merchant/customers/{customer_id}/approve` or `/reject`.

## Route Table

| Method | Mounted path | Token | Permission | Success |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/customer/documents` | onboarding or full Customer | owner | 201 |
| GET | `/api/v1/customer/documents/{file_id}/url` | onboarding or full Customer | owner | 200 |
| GET | `/api/v1/customer/documents/{file_id}/content` | owner + signed token | owner | 200 |
| POST | `/api/v1/customer/registration/profile` | onboarding | applicant | 201 |
| GET | `/api/v1/customer/registration/profile` | onboarding | applicant | 200 |
| PATCH | `/api/v1/customer/registration/profile` | onboarding | applicant | 200 |
| POST | `/api/v1/customer/registration/submit` | onboarding | applicant | 200 |
| GET | `/api/v1/customer/registration/status` | onboarding | applicant | 200 |
| GET | `/api/v1/customer/profile` | full Customer | approved owner | 200 |
| POST | `/api/v1/merchant/documents` | Merchant | session | 201 |
| POST | `/api/v1/merchant/customers` | Merchant | `customers.create` | 201 |
| GET | `/api/v1/merchant/customers` | Merchant | `customers.view` | 200 |
| GET | `/api/v1/merchant/customers/{customer_id}` | Merchant | `customers.view` | 200 |
| GET | `/api/v1/merchant/customers/{customer_id}/eligibility` | Merchant | `orders.create` | 200 |
| GET | `/api/v1/merchant/kyc/applications` | Merchant | `customers.review` | 200 |
| GET | `/api/v1/merchant/kyc/applications/{application_id}` | Merchant | `customers.review`, `customer_documents.review` | 200 |
| GET | `/api/v1/merchant/documents/{file_id}/url` | Merchant | `customers.review`, `customer_documents.review` | 200 |
| GET | `/api/v1/merchant/documents/{file_id}/content` | Merchant + signed token | reviewer | 200 |
| POST | `/api/v1/merchant/customers/{customer_id}/approve` | Merchant | `customers.approve` | 200 |
| POST | `/api/v1/merchant/customers/{customer_id}/reject` | Merchant | `customers.reject` | 200 |

## Headers

Use `Authorization: Bearer <token>` on every protected route. Document upload uses `multipart/form-data` with `file` and `type`. JSON routes use `Content-Type: application/json`.

## Important Error Codes

Use `detail.code` for logic. Do not parse `detail.message`.

Important codes: `AUTH_REQUIRED`, `TOKEN_TYPE_NOT_ALLOWED`, `TOKEN_CHANNEL_MISMATCH`, `ACCOUNT_PENDING_APPROVAL`, `ACCOUNT_REJECTED`, `PERMISSION_DENIED`, `VALIDATION_ERROR`, `REGISTRATION_INCOMPLETE`, `REGISTRATION_PROFILE_EXISTS`, `REGISTRATION_PROFILE_NOT_FOUND`, `MERCHANT_CODE_INVALID`, `CUSTOMER_NOT_FOUND`, `APPLICATION_NOT_FOUND`, `DOCUMENT_NOT_FOUND`, `DOCUMENT_URL_EXPIRED`, `DOCUMENTS_PENDING_APPROVAL`, `DOCUMENT_SCAN_PENDING`, `INVALID_STATUS_TRANSITION`, `REJECTION_REASON_REQUIRED`.

## Environment Values

Mobile/Postman variables: `baseUrl`, `customer_onboarding_token`, `customer_access_token`, `merchant_access_token`, `customer_id`, `application_id`, `file_id`.

Backend production values: set `DOCUMENT_ENCRYPTION_SECRET`, bind a production `DOCUMENT_STORAGE_PROVIDER`, keep `ALLOW_SKIPPED_KYC_SCAN_IN_LOCAL` disabled outside local/test, and schedule orphan cleanup after dry-run review.

## Known Limitations

- Production storage provider is not yet selected.
- `DOCUMENT_ENCRYPTION_SECRET` is required outside local development.
- Real malware scanner is not connected yet; staging/production approval requires `CLEAN`.
- Order/invoice values in Customer responses may be absent or default until those modules exist.
- Pricing, Orders, Delivery, Inventory, Payments, Expenses, Reports, Notifications and Dashboards are outside this handover.

## Test Evidence

- `python -m pytest -q`: 508 passed.
- `python -m pytest -q tests/integration/authentication tests/unit/authentication tests/api`: 212 passed.
- `python -m pytest -q tests/integration/customers/test_kyc_review.py tests/integration/customers/test_document_upload.py`: 36 passed.
- `python -m pytest -q tests/unit/customers tests/unit/shared`: 137 passed.
- Alembic downgrade and upgrade for `20260921_0012` succeeded.

## Integration Checklist

- Keep separate secure storage entries for onboarding tokens and full Customer tokens.
- Route pending full-login `ACCOUNT_PENDING_APPROVAL` to onboarding status.
- Upload documents before profile save.
- Send document `fileId` as `documents[].fileName`.
- Use `numberMasked` for document display.
- Use `/customer/profile` only after full Customer login succeeds.
- Merchant app must request the seeded permissions listed in `docs/mobile-field-mapping.md`.
- Use generated OpenAPI files and Postman collections from this handover.

