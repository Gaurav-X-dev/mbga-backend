# Customer Approval Workflow

Customer applications must be scoped to an identifiable Merchant.

```mermaid
sequenceDiagram
  participant Customer
  participant API
  participant Merchant
  Customer->>API: Submit profile and mandatory documents
  API-->>Customer: UNDER_REVIEW
  Merchant->>API: Review application in Merchant scope
  Merchant->>API: Approve or reject documents
  Merchant->>API: Approve or reject customer
```

Approval permissions are dynamic:

- `customers.review`
- `customers.approve`
- `customers.reject`
- `customer_documents.review`
- `customer_documents.approve`
- `customer_documents.reject`

Scope checks must prevent cross-Merchant access.
