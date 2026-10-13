# Merchant and Customer Credit API

## Merchant: update customer credit terms

`PATCH /api/v1/merchant/credit/customers/{customerId}`

Authentication: Merchant bearer token. The signed-in staff member needs `credit.manage`.
Managers receive this permission from the RBAC seed. A merchant can update only a customer
linked to that same merchant; another merchant's customer returns `404 CUSTOMER_NOT_FOUND`.

Request:

```json
{
  "creditEnabled": true,
  "creditLimit": 25000,
  "creditDays": 15,
  "reason": "Approved by agency owner"
}
```

Response:

```json
{
  "customerId": "customer-uuid",
  "creditEnabled": true,
  "creditLimit": 25000,
  "creditDays": 15,
  "usedCredit": 8000,
  "availableCredit": 17000
}
```

Every change is recorded in the credit audit table and general audit log with the merchant
user, merchant, reason, old terms, new terms and timestamp.

## Read-only fields for Merchant and Customer apps

These existing endpoints now return the same credit fields:

- `GET /api/v1/merchant/customers`
- `GET /api/v1/merchant/customers/{customerId}`
- `GET /api/v1/customer/profile`

Fields:

```json
{
  "creditEnabled": true,
  "creditLimit": 25000,
  "creditDays": 15,
  "usedCredit": 8000,
  "availableCredit": 17000,
  "creditActive": true,
  "lastOrderAt": "2026-10-13T10:30:00Z"
}
```

`creditActive` is true only when both the platform credit feature and the customer's credit
terms are enabled. The Customer app must display these values read-only. `lastOrderAt` is now
calculated from the customer's real latest order instead of always returning null.

Admin credit endpoints and their behavior are unchanged.
