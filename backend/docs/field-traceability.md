# Field Traceability

Primary source: `MBGA_Screen_Field_Role_Specification-2.xlsx`

Reviewed worksheets:

- `Merchant App`
- `Customer App`
- `Delivery App`
- `Role Access Matrix (Sec.10)`

Supporting sources:

- `MBGA_SRS_Phase1_Redesigned_No_Duplicacy_2026-09-04.docx`
- `SoW-Order Management and Payment Recon System for MBGA (2).docx`

## Implemented Technical Fields

| Area | API field | Database field | Source | Status |
| --- | --- | --- | --- | --- |
| OTP | `mobile_number` | `otp_challenges.mobile_number` | Confirmed OTP login requirement | SYSTEM_REQUIRED_ADDED |
| OTP | `purpose` | `otp_challenges.purpose` | Confirmed purpose binding | SYSTEM_REQUIRED_ADDED |
| OTP | `login_channel` | `otp_challenges.login_channel` | Confirmed channel binding | SYSTEM_REQUIRED_ADDED |
| OTP | `request_id` | `otp_challenges.id` | Confirmed request/verify contract | SYSTEM_REQUIRED_ADDED |
| Merchant | `merchant_code` | `merchants.code` | Merchant association requirement | SYSTEM_REQUIRED_ADDED |
| Customer | `merchant_id` | `customer_profiles.merchant_id` | Scoped approval requirement | SYSTEM_REQUIRED_ADDED |
| Customer document | `document_type` | `customer_documents.document_type` | Excel/SRS document requirement | SYSTEM_REQUIRED_ADDED |

## Review-Required Fields

| Area | Field | Reason | Safe behavior |
| --- | --- | --- | --- |
| Customer onboarding | `merchant_id` / `merchant_code` | Exact association source is not confirmed in Excel/SRS/SOW | Required by backend design, documented for review, no global approval fallback |
