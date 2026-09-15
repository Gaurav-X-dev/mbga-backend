# Customer Registration

Customer registration is separate from full login.

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> MOBILE_VERIFIED
  MOBILE_VERIFIED --> PROFILE_INCOMPLETE
  PROFILE_INCOMPLETE --> DOCUMENTS_PENDING
  DOCUMENTS_PENDING --> UNDER_REVIEW
  UNDER_REVIEW --> APPROVED
  UNDER_REVIEW --> REJECTED
  REJECTED --> DOCUMENTS_PENDING
  APPROVED --> SUSPENDED
  SUSPENDED --> APPROVED
```

OTP verification does not approve a customer. Before approval, only restricted onboarding APIs are available.
