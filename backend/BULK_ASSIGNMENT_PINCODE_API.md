# Pincode-wise bulk order assignment

The existing `POST /api/v1/merchant/orders/confirm` remains unchanged for older app builds.
The new bulk sheet should use the two endpoints below.

## 1. Preview selected orders

`POST /api/v1/merchant/orders/bulk-assignment/preview`

```json
{"orderIds":["order-id-1","order-id-2"]}
```

The response automatically groups orders by the delivery-address pincode. Every group contains
its orders, totals, and only the active vehicles mapped to that pincode. `canAssign` is false with
a `blockedReason` when the address has no pincode or the pincode has no mapped vehicle.

## 2. Confirm all groups

`POST /api/v1/merchant/orders/bulk-assignment/confirm`

```json
{
  "groups": [
    {
      "orderIds": ["order-id-1", "order-id-2"],
      "delivery": {
        "vehicleNumber": "HR26 DQ 9918",
        "driverUserId": "driver-user-id",
        "deliveryDate": "2026-10-14"
      }
    }
  ]
}
```

All groups are processed in one database transaction. An order cannot occur in two groups, a
group cannot mix pincodes, and the backend re-checks vehicle coverage during confirmation.
There is no zone or trip master in this flow.

The same routes are also exposed under `/api/v1/admin/orders/...` with admin merchant scope.
