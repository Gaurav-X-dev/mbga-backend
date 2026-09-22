# Merchant Customer and KYC API Guide

Base URL: `{{baseUrl}}/api/v1`

Use the existing Merchant auth flow. All routes require a Merchant access token. Merchant isolation is enforced from the authenticated Merchant context; foreign Customer, KYC application and document IDs behave as not found where disclosure would leak existence.

## Routes

| API | Permission | Purpose |
| --- | --- | --- |
| `POST /merchant/documents` | Merchant session | Upload staged Customer KYC document |
| `POST /merchant/customers` | `customers.create` | Create Retail or Industrial Customer and pending KYC application |
| `GET /merchant/customers` | `customers.view` | List Customers |
| `GET /merchant/customers/{customer_id}` | `customers.view` | Customer detail |
| `GET /merchant/customers/{customer_id}/eligibility` | `orders.create` | Order eligibility |
| `GET /merchant/kyc/applications` | `customers.review` | KYC queue |
| `GET /merchant/kyc/applications/{application_id}` | `customers.review` + `customer_documents.review` | KYC detail |
| `GET /merchant/documents/{file_id}/url` | `customers.review` + `customer_documents.review` | Signed document URL |
| `GET /merchant/documents/{file_id}/content` | same reviewer plus signed token | Stream document |
| `POST /merchant/customers/{customer_id}/approve` | `customers.approve` | Approve pending application |
| `POST /merchant/customers/{customer_id}/reject` | `customers.reject` | Reject pending application |

## Create Customer

`POST /merchant/customers` uses the same body shape as Customer registration, with `mobile` supplied by authorized staff. Merchant ID is never accepted from the request body.

Documents are uploaded first to `/merchant/documents`, then referenced by `fileName` in the create request. Approval remains a separate reviewer action.

## Review

List applications with `GET /merchant/kyc/applications?status=PENDING|APPROVED|REJECTED|ALL`. Open detail with `GET /merchant/kyc/applications/{application_id}`. Document identifiers in list/detail are masked as `numberMasked`; physical storage paths are never returned.

Approve with empty body: `POST /merchant/customers/{customer_id}/approve`.

Reject with:

```json
{"reason": "The PAN card image is unreadable"}
```

## Filters and Responses

Customer list supports account-status filtering and search as implemented by the OpenAPI document. `CustomerResponse` includes `id`, `code`, `customerType`, `businessName`, `ownerName`, `mobile`, `email`, `deliveryAddress`, `documents`, `sites`, `accountStatus`, `kycStatus`, `pricingTier`, `approvedAt`, `registeredAt`, and current placeholder order/balance fields.

## Errors

Use `detail.code` for logic. Important codes: `CUSTOMER_NOT_FOUND`, `APPLICATION_NOT_FOUND`, `PERMISSION_DENIED`, `INVALID_STATUS_TRANSITION`, `REGISTRATION_INCOMPLETE`, `DOCUMENTS_PENDING_APPROVAL`, `DOCUMENT_SCAN_PENDING`, `REJECTION_REASON_REQUIRED`, `VALIDATION_ERROR`, `DOCUMENT_NOT_FOUND`, `DOCUMENT_URL_EXPIRED`.

