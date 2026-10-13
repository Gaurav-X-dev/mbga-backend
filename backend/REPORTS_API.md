# Merchant Reports API

## Endpoints

- `GET /api/v1/merchant/reports`
- `GET /api/v1/merchant/reports/export`
- `GET /api/v1/admin/reports`
- `GET /api/v1/admin/reports/export`

Merchant endpoints require a Merchant-channel token and are always restricted to that
merchant. Admin endpoints require an Admin-channel token plus report permissions. Super Admin
receives every permission and can view all merchants; pass `merchantId` to restrict an Admin
report to one merchant. Customer and Delivery tokens are rejected.

## Query parameters

- `type` (required): `DAILY_DELIVERY`, `PAYMENT_COLLECTION`, `PENDING_PICKUP`, `EXPENSE`,
  `STOCK_MOVEMENT`, `PROFIT_LOSS`, `TAX_GST`
- `from`, `to`: ISO-8601 timestamps. Defaults to the current business day. Maximum range is
  3660 days.
- `customerId`: supported by delivery, payment, pending-pickup and tax reports.
- `godownId`: deliberately rejected until a godown entity exists. It is never silently ignored.
- `merchantId` (Admin endpoints only): optional merchant scope. When omitted, the report covers
  all merchants and each row includes `merchantId` and a human-readable `merchant` name.
- `format` (export only): `CSV`, `EXCEL`, `XLSX`, `XML`, `XAML`, `JSON`

## Permissions

- All reads: `reports.view`
- All exports: `reports.view` and `reports.export`
- Expense and Profit/Loss: additionally `expenses.view`
- Payment Collection drill-down/audit: additionally `payments.reconcile`

Every Merchant-channel database query includes `merchant_id` from the authenticated Merchant
session; Merchant identity is never accepted from its request parameters. Only the
Admin-channel endpoints may select `merchantId`; omission there deliberately selects the
platform-wide scope.

## Correctness notes

- Delivery figures come from delivery slips and their recorded per-cylinder handover counts.
- `id`, `merchantId`, `customerId` and `referenceId` are internal action/drill-down keys. Apps
  must display `displayId`, `merchant`, `customer`, `slip`, `payment`, `invoice` or `reference`.
- Report timestamps and generated periods serialize with the `+05:30` India offset. Default
  ranges cover midnight-to-midnight in `Asia/Kolkata`, while database timestamps remain UTC.
- Delivery-backed stock movements expose the delivery slip number in `reference`; the original
  UUID remains available only as `referenceId`.
- Payment totals exclude `INVALID` payments.
- Pending pickup is delivered cylinders minus empties collected, per completed slip.
- Profit/Loss uses invoice taxable revenue (GST excluded) minus recorded operating expenses.
- GST outward tax comes from immutable invoice values. Expenses do not currently record input
  GST, so the API returns `inputItcStatus: NOT_RECORDED` and does not invent an ITC figure.
- This deployment has a merchant-level stock ledger, not multiple godowns.

## Export security

- No exported file is persisted on the API server.
- CSV/XLSX cells are protected against spreadsheet formula injection.
- Responses use `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`.
- Drill-down objects are excluded from tabular exports.
