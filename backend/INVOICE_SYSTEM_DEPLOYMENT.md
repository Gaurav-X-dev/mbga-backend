# Universal Invoice System — Deployment and App Contract

## What is delivered

One invoice document contract is available on all three channels.  It is the same invoice data
and the same printable A4 layout, with tenant access enforced by the existing channel token:

| User | JSON document | Printable HTML |
|---|---|---|
| Merchant | `GET /api/v1/merchant/invoices/{invoiceId}/document` | `GET /api/v1/merchant/invoices/{invoiceId}/document.html` |
| Customer | `GET /api/v1/customer/invoices/{invoiceId}/document` | `GET /api/v1/customer/invoices/{invoiceId}/document.html` |
| Admin | `GET /api/v1/admin/invoices/{invoiceId}/document?merchantId={merchantId}` | `GET /api/v1/admin/invoices/{invoiceId}/document.html?merchantId={merchantId}` |

The customer can only fetch their own invoice.  Merchant staff can fetch their merchant's
invoices.  Admin must explicitly choose `merchantId`; this prevents cross-merchant data leaks.

## Document behavior

- `RETAIL` customers receive a `CASH_MEMO` layout.
- `INDUSTRIAL` customers receive a `TAX_INVOICE` layout with GST buyer/consignee, dispatch and
  e-Way/IRN sections.
- Same-state invoices show CGST + SGST; interstate invoices show IGST.
- Every new invoice saves a full issue-time snapshot of party names, addresses, GSTIN, cylinders,
  prices, tax and delivery facts.  Editing a profile or rate later cannot modify old invoices.
- Old invoices from before this deployment remain viewable, marked `isLegacySnapshot: true`.
- `verificationQrData` is an internal verification value only; it is not an official GST IRN QR.

## Merchant invoice template settings

Merchant admin/finance staff can configure branding and print details:

- `GET /api/v1/merchant/invoice-settings`
- `PATCH /api/v1/merchant/invoice-settings`

Admin can inspect/update a selected merchant's settings using the same paths with
`?merchantId={merchantId}` and an Admin token.

Supported fields: `invoicePan`, `invoiceBankName`, `invoiceBankAccountName`,
`invoiceBankAccountNumber`, `invoiceBankIfsc`, `invoiceLogoUrl`, `invoiceSignatureUrl`,
`invoiceTerms`, `invoiceDeclaration`, `invoiceHsnSac`.

Those settings are copied into invoices issued after the change.  They do not alter old invoices.

## Manual e-Way / e-Invoice references

No government e-Invoice/e-Way provider is integrated in this release.  Merchant or Admin can
record references after obtaining them externally:

`PATCH /api/v1/merchant/invoices/{invoiceId}/compliance`

For Admin add the normal `?merchantId={merchantId}` query.  Body example:

```json
{
  "irn": "...",
  "acknowledgementNumber": "...",
  "ewayBillNumber": "...",
  "transportDocumentNumber": "...",
  "lrNumber": "...",
  "termsOfDelivery": "Door delivery"
}
```

## Deployment

Run `alembic upgrade head` before restarting the backend.  The migration is
`20261012_0041_invoice_documents`.
