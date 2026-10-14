# Payment Proof APIs

The Delivery app uploads UPI evidence once. Merchant, Customer and Admin apps then read the
same private file through their own authenticated channel. The storage key is never exposed.

## Delivery app

- `POST /api/v1/delivery/deliveries/{deliveryId}/generate-qr`
- `POST /api/v1/delivery/deliveries/{deliveryId}/payment-proof`
- `POST /api/v1/delivery/deliveries/{deliveryId}/confirm`
- `GET /api/v1/delivery/deliveries/{deliveryId}/completed-detail`

## Merchant app

- `GET /api/v1/merchant/payments`
- `GET /api/v1/merchant/payments/{paymentId}`
- `GET /api/v1/merchant/payments/{paymentId}/proof`

The first two endpoints return `proofUrl` and `proofCapturedAt`. `proofUrl` points to the third
endpoint and must be fetched with the Merchant bearer token.

## Customer app

- `GET /api/v1/customer/payments`
- `GET /api/v1/customer/payments/{paymentId}`
- `GET /api/v1/customer/payments/{paymentId}/proof`

Only the signed-in customer's payments and proofs are visible.

## Admin web panel

- `GET /api/v1/admin/payments?merchantId={merchantId}`
- `GET /api/v1/admin/payments/{paymentId}?merchantId={merchantId}`
- `GET /api/v1/admin/payments/{paymentId}/proof?merchantId={merchantId}`

Admin keeps the existing merchant scope selection. The proof endpoint uses the same scope.

## Frontend image handling

The proof endpoint returns raw `image/jpeg` or `image/png`, not JSON. Send the same bearer token
used by the payment API. React Native should fetch it as a blob/file and render the resulting
local URI; a plain unauthenticated image URL will return `401`.

If no proof exists, or the payment belongs to another customer/merchant, the endpoint returns
`404 PAYMENT_PROOF_NOT_FOUND` or `404 PAYMENT_NOT_FOUND` without exposing another tenant's data.
