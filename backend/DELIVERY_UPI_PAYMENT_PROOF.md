# Delivery App: UPI QR and Payment Proof

UPI collection now follows this order:

1. Generate a QR using `POST /api/v1/delivery/deliveries/{deliveryId}/generate-qr`.
2. Upload the payment screenshot/photo using
   `POST /api/v1/delivery/deliveries/{deliveryId}/payment-proof`.
3. Send the returned `proofUrl` and `capturedAt` in the delivery confirm request.

All endpoints require the driver's Delivery App bearer token and only accept a delivery assigned
to that driver.

## Upload proof

`POST /api/v1/delivery/deliveries/{deliveryId}/payment-proof`

Content type: `multipart/form-data`

- `file`: JPEG or PNG, maximum 5 MB.
- `capturedAt`: ISO-8601 timestamp, for example `2026-10-13T14:30:00Z`.

Response data:

```json
{
  "proofUrl": "/api/v1/delivery/deliveries/DELIVERY_ID/payment-proof",
  "capturedAt": "2026-10-13T14:30:00.000Z"
}
```

The standard delivery response-envelope middleware may wrap this as
`{"success": true, "data": ...}` in environments where that envelope is enabled.

## Confirm delivery

`POST /api/v1/delivery/deliveries/{deliveryId}/confirm`

```json
{
  "deliveredItems": [{"cylinderType": "LPG_19KG", "quantity": 1}],
  "collectedEmpties": [],
  "payment": {
    "method": "UPI",
    "split": "full",
    "amountCollected": 1800,
    "payableAmount": 1800,
    "pendingBalance": 0,
    "proofUrl": "/api/v1/delivery/deliveries/DELIVERY_ID/payment-proof",
    "proofCapturedAt": "2026-10-13T14:30:00.000Z"
  }
}
```

For a positive UPI collection, confirmation is rejected unless a QR was generated for the same
delivery and exact collected amount, and an image proof was uploaded for that delivery. Cash and
zero-amount collections are unchanged.

`GET /api/v1/delivery/deliveries/{deliveryId}/completed-detail` exposes `payment.proofUrl` and
`payment.proofCapturedAt`. The proof image itself can be read through `GET` on the returned URL
using the same driver's token.

