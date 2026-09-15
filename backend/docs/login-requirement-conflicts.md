# Login Requirement Conflicts And Safe Behavior

## Customer To Merchant Association

- Source: implementation request, Excel Customer App sheet, SRS/SOW customer onboarding requirements.
- Conflict/open item: customer approval must belong to an identifiable Merchant, but the reviewed source sheets do not expose one confirmed canonical association field.
- Candidate fields: `merchant_id`, `merchant_code`, dealer code, distributor code, referral/invitation code.
- Selected safe behavior: add proposed system-required fields `merchant_id` and `merchant_code` for backend traceability, mark them review-required, and do not allow globally unscoped customer approval.
- Access impact: approvers may only review customers in their authorized Merchant scope unless they later receive an explicit global permission.

## OTP Verification Versus Full Login

- Source: implementation request and SRS customer onboarding.
- Potential confusion: OTP verification can identify/control a mobile number but must not imply customer approval.
- Selected safe behavior: keep OTP verification, onboarding access, profile completion, document submission, approval, and full login as separate states.

## React Web Panel Access

- Source: implementation request.
- Clarification: React Web Panel is shared by Super Admin and authorized Merchant/staff users only.
- Selected safe behavior: no Customer or Delivery web-panel screens.
