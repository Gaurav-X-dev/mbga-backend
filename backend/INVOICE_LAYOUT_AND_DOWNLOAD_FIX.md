# Invoice layout and Admin download fix

## What changed

- `GET /api/v1/{merchant|customer|admin}/invoices/{invoiceId}/document.html` now renders the A4 GST tax-invoice layout shared by all three applications.
- `GET /api/v1/{merchant|customer|admin}/invoices/{invoiceId}/document.pdf` downloads a PDF with `Content-Disposition: attachment`.
- `GET /api/v1/{merchant|customer|admin}/invoices/{invoiceId}/document/download` is a compatible download alias.

## Data and compliance

- The invoice uses the immutable snapshot stored when the invoice is issued, so later changes to merchant, customer, address or price do not alter old invoices.
- IRN, acknowledgement and e-Way Bill fields remain blank/not generated until entered manually or a GST/e-Way Bill provider is integrated.
- The QR shown is an internal invoice verification QR. It is not presented as an official government e-invoice QR.

## Frontend use

- For the exact print layout, open `document.html` in a browser/webview and use Print / Save as PDF.
- For a direct file download button, open `document.pdf` (or `document/download`) with the existing bearer token. This PDF is rendered from the same HTML template.
