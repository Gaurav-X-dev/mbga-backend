# Customer API Integration Guide

Base URL: `{{baseUrl}}/api/v1`

Authentication is the existing Customer authentication contract. Pending registrations use the onboarding token from `/customer/registration/otp/verify`; approved Customers use the full access token from `/customer/auth/otp/verify`. A pending Customer full-login request returning `ACCOUNT_PENDING_APPROVAL` is expected.

## Token Use

| API | Token |
| --- | --- |
| `POST /customer/documents` | onboarding or full Customer token |
| `GET /customer/documents/{file_id}/url` | owner onboarding or full Customer token |
| `GET /customer/documents/{file_id}/content` | owner token plus signed `token` query |
| `POST /customer/registration/profile` | onboarding token |
| `GET /customer/registration/profile` | onboarding token |
| `PATCH /customer/registration/profile` | onboarding token |
| `POST /customer/registration/submit` | onboarding token |
| `GET /customer/registration/status` | onboarding token |
| `GET /customer/profile` | approved full Customer token |
| `GET /customer/auth/me` | existing auth identity endpoint |

## First-Time Registration

1. Request and verify OTP on `/customer/registration/otp/request` and `/customer/registration/otp/verify`.
2. Store the returned onboarding access/refresh tokens separately from full-login tokens.
3. Upload required documents with `POST /customer/documents`.
4. Save the profile with `POST /customer/registration/profile`.
5. Read or update the draft with `GET` or `PATCH /customer/registration/profile`.
6. Submit with `POST /customer/registration/submit`.
7. Poll or refresh screen state with `GET /customer/registration/status`.
8. After approval, logout or discard onboarding tokens and run the existing full Customer login flow.
9. Read approved business profile with `GET /customer/profile`.

## Retail Profile Request

```json
{
  "merchant_code": "T-ABC123",
  "customerType": "RETAIL",
  "businessName": "Sharma Stores",
  "ownerName": "Ravi Sharma",
  "email": "ravi@example.invalid",
  "deliveryAddress": {
    "line1": "12 MG Road",
    "line2": "Near bus stand",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452001"
  },
  "documents": [
    {"type": "AADHAAR", "number": "123412341234", "fileName": "{{aadhaarFileId}}"},
    {"type": "PAN", "number": "ABCDE1234F", "fileName": "{{panFileId}}"}
  ]
}
```

## Industrial Profile Request

```json
{
  "merchant_code": "T-ABC123",
  "customerType": "INDUSTRIAL",
  "businessName": "Apex Foods",
  "ownerName": "Nisha Mehta",
  "email": "ops@example.invalid",
  "deliveryAddress": {
    "line1": "Plot 22",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452001"
  },
  "documents": [
    {"type": "FSSAI", "number": "12345678901234", "fileName": "{{fssaiFileId}}"},
    {"type": "GST", "number": "23AAACA1234F1Z5", "fileName": "{{gstFileId}}"}
  ],
  "sites": [
    {
      "name": "Plant A",
      "address": {"line1": "Plot 22", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001"},
      "contactName": "Ramesh Patil",
      "contactMobile": "9822001122",
      "isPrimary": true
    }
  ]
}
```

## Field Rules

Retail requires `AADHAAR` exactly 12 digits and `PAN` matching `^[A-Z]{5}[0-9]{4}[A-Z]$`. Industrial requires `FSSAI` exactly 14 digits, `GST` matching the API spec GSTIN regex, and exactly one primary site. Default `pricingTier` is `STANDARD`.

Mobile number comes from the onboarding identity; a conflicting request mobile is rejected. Status, pricing tier, Customer code and timestamps are server-managed.

## Status and Errors

Use `detail.code` for logic; `detail.message` is display text. Map `detail.fields[]` to form fields by `field`.

Important codes: `ACCOUNT_PENDING_APPROVAL`, `ACCOUNT_REJECTED`, `REGISTRATION_INCOMPLETE`, `REGISTRATION_PROFILE_NOT_FOUND`, `REGISTRATION_PROFILE_EXISTS`, `MERCHANT_CODE_INVALID`, `DOCUMENTS_PENDING_APPROVAL`, `DOCUMENT_SCAN_PENDING`, `VALIDATION_ERROR`, `TOKEN_TYPE_NOT_ALLOWED`, `TOKEN_CHANNEL_MISMATCH`.

Status-to-screen: `COMPLETE_PROFILE` -> registration form, `WAIT_FOR_APPROVAL` -> pending screen, `SIGN_IN` -> full login, `CONTACT_SUPPORT` -> support screen, `OPEN_CUSTOMER_HOME` -> home.

