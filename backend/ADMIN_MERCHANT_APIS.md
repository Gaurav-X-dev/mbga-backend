# Complete Admin API mirror for Merchant operations

The Merchant application is unchanged. All **87 non-auth Merchant operations** now have an
Admin-channel counterpart under `/api/v1/admin` for the web panel.

## Base URLs

- Merchant (unchanged): `/api/v1/merchant`
- Admin web panel: `/api/v1/admin`
- Admin OpenAPI: `/openapi/admin.json`
- Admin Swagger: `/docs/admin`

Request and response models remain the same, so the Admin frontend can reuse Merchant feature
types and forms.

## Security model

Business operations for a merchant require:

1. An access token issued by `/api/v1/admin/auth/*`.
2. The required domain permission.
3. `merchants.view` permission.
4. A required `merchantId=<merchant UUID>` query parameter.

The selected merchant is resolved on the server and injected into the existing tenant-scoped
business services. Merchant identifiers in request bodies are not trusted. Trying to access a
resource owned by another merchant returns `404`.

Super Admin has all permissions. Restricted Admin roles only see modules covered by their
assigned permissions.

Example:

```http
GET /api/v1/admin/payments?merchantId=<merchant-uuid>&reconciliationStatus=PENDING
Authorization: Bearer <admin-access-token>
```

## Admin web-panel modules

The Admin channel now includes the complete Merchant feature set:

- Customers: create, list, detail and order eligibility
- Customer approval and rejection
- KYC queue, statistics and application detail
- Customer documents: upload, signed URL and secure content stream
- Standard pricing months, entries and change logs
- Customer-specific pricing overrides
- Orders: create, list, quote, repeat, reorder, confirm, bulk confirm and cancel
- Invoices and customer payment summaries
- Payments: list, record, detail and reconciliation
- Expenses and dynamic expense categories
- Inventory snapshot and stock movements
- Deliveries and reassignment
- Delivery users: create, list, available crew, update, activate, block and unblock
- Vehicles: create, list, available vehicles and update
- Tasks, messages, activity and team directory
- Reports and exports
- Notifications and read state
- Constants, states and cities

## Scope exceptions

- `/api/v1/admin/notifications*` shows notifications addressed to the signed-in Admin user or
  Admin channel. It does not impersonate a merchant notification inbox and therefore does not
  take `merchantId`.
- `/api/v1/admin/constants` and `/api/v1/admin/locations*` are shared catalogue APIs and do not
  take `merchantId`.
- `/api/v1/admin/kyc/applications*` is the existing head-office cross-merchant KYC queue. Its
  list supports an optional merchant filter because Super Admin may intentionally view all KYC.
- Admin document upload and URL operations require `merchantId`. A locally streamed signed
  document URL automatically includes that same merchant scope.

## Compatibility and deployment

- No Merchant endpoint was removed, renamed or redirected.
- Customer and Delivery application contracts are unchanged.
- No database migration is required for this API expansion.
- Every Admin copy appears in Admin Swagger/OpenAPI.
