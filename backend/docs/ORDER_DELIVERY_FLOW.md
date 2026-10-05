# Customer, Merchant and Delivery Apps: Order-to-Delivery API Handoff

Share this one document with all three frontend teams. It contains the final order-to-delivery
contract, the endpoints each app must call, request examples, notifications, removed APIs, and
the UI changes required in each app.

Scope: customer order placement/tracking, merchant order management/assignment, driver delivery,
and the notification endpoints used by this flow. Unrelated admin, KYC, pricing, expense, and
accounting APIs are intentionally outside this document.

## Common API rules

- Base prefix: `/api/v1`
- Header on authenticated calls: `Authorization: Bearer <accessToken>`
- JSON field names are camelCase.
- Dates use `YYYY-MM-DD`; timestamps are UTC ISO strings ending in `Z`.
- Send a unique `Idempotency-Key` header when placing/repeating an order. Retrying with the same
  key returns the original order instead of creating a duplicate.
- Merchant order APIs require a merchant token, customer APIs a customer token, and delivery APIs
  a delivery-app token. Tokens are not interchangeable.
- A resource outside the signed-in merchant/customer/driver scope normally returns `404`, not
  `403`, to avoid leaking another account's ids.
- Delivery responses are raw JSON by default. If deployment enables
  `DELIVERY_RESPONSE_ENVELOPE=true`, a success becomes `{"success": true, "data": ...}` and an
  error becomes `{"success": false, "error": ...}`. Do not enable this flag until the Delivery
  App team confirms it expects the wrapper.

## Status flow

```text
PLACED
  -> CONFIRMED (merchant confirms and assigns vehicle/crew atomically)
  -> OUT_FOR_DELIVERY (driver starts one delivery or a whole round)
  -> ON_LOCATION (driver taps "I am on location")
  -> DELIVERED (driver records counts, then verifies customer OTP)
  -> CANCELLED (alternative terminal path: driver verifies customer OTP and cancels)
```

The delivery slip follows `SCHEDULED -> DISPATCHED -> ON_LOCATION -> DELIVERED|FAILED`.
`ON_LOCATION` may be skipped by an older Delivery App build so completion remains backward
compatible. `SCHEDULED` is an internal assignment state; there is no separate merchant Schedule
or Reschedule API.

## Endpoint inventory by app

### Customer App

| Method | Endpoint | Use |
|---|---|---|
| GET | `/api/v1/customer/orders/statuses` | Build status chips/timeline from backend metadata |
| GET | `/api/v1/customer/orders/cutoff` | Show today's cutoff and expected delivery date |
| POST | `/api/v1/customer/orders/quote` | Price basket before placement |
| POST | `/api/v1/customer/orders` | Place order |
| GET | `/api/v1/customer/orders?status=&search=` | Customer's order list |
| GET | `/api/v1/customer/orders/{orderId}` | Order detail/tracking |
| POST | `/api/v1/customer/orders/{orderId}/cancel` | Cancel only before out-for-delivery |
| GET | `/api/v1/customer/orders/repeat` | Preview last order at today's prices |
| POST | `/api/v1/customer/orders/repeat` | Repeat last order |
| GET | `/api/v1/customer/orders/{orderId}/reorder` | Preview a selected old order |
| POST | `/api/v1/customer/orders/{orderId}/reorder` | Place selected old order again |
| GET | `/api/v1/customer/notifications` | Notification list |
| GET | `/api/v1/customer/notifications/unread-count` | Bell badge |
| GET | `/api/v1/customer/notifications/{notificationId}` | Notification detail |
| POST | `/api/v1/customer/notifications/{notificationId}/read` | Mark one notification read |
| POST | `/api/v1/customer/notifications/read-all` | Mark all read |

The customer app has no confirm, assign, dispatch, deliver, or delivery-cancel API.

### Merchant App

| Method | Endpoint | Permission/use |
|---|---|---|
| GET | `/api/v1/merchant/orders/statuses` | `orders.view`; order status catalogue |
| GET | `/api/v1/merchant/orders/cutoff` | `orders.view`; cutoff and expected date |
| POST | `/api/v1/merchant/orders/quote` | `orders.create`; quote for a customer |
| POST | `/api/v1/merchant/orders` | `orders.create`; place order for customer |
| GET | `/api/v1/merchant/orders?customerId=&status=&search=` | `orders.view`; order listing |
| GET | `/api/v1/merchant/orders/{orderId}` | `orders.view`; detail |
| POST | `/api/v1/merchant/orders/{orderId}/confirm` | `orders.update`; confirm + assign one |
| POST | `/api/v1/merchant/orders/confirm` | `orders.update`; confirm + assign up to 50 |
| POST | `/api/v1/merchant/orders/{orderId}/cancel` | `orders.cancel`; cancel before trip starts |
| GET/POST | `/api/v1/merchant/orders/repeat` | Preview/place customer's last order |
| GET/POST | `/api/v1/merchant/orders/{orderId}/reorder` | Preview/place selected old order |
| GET | `/api/v1/merchant/delivery-users/available?delivery_user_type=DRIVER` | Driver picker |
| GET | `/api/v1/merchant/delivery-users/available?delivery_user_type=HELPER` | Helper picker |
| GET | `/api/v1/merchant/deliveries?status=&search=` | `delivery.view`; read-only delivery board |
| GET | `/api/v1/merchant/deliveries/{deliveryId}` | `delivery.view`; slip detail |
| GET | `/api/v1/merchant/notifications` | Merchant notification list |
| GET | `/api/v1/merchant/notifications/unread-count` | Bell badge |
| GET | `/api/v1/merchant/notifications/{notificationId}` | Notification detail |
| POST | `/api/v1/merchant/notifications/{notificationId}/read` | Mark one read |
| POST | `/api/v1/merchant/notifications/read-all` | Mark all read |

### Delivery App

| Method | Endpoint | Use |
|---|---|---|
| GET | `/api/v1/delivery/deliveries/today` | Today's assigned queue |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/out-for-delivery` | Start one delivery |
| POST | `/api/v1/delivery/deliveries/out-for-delivery` | Start one or many deliveries |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/verify-location` | Driver: I am on location |
| PUT | `/api/v1/delivery/deliveries/{deliveryId}/update-items` | Update delivery item counts/reason |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/generate-qr` | Generate payment QR |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/confirm` | Record delivered/empty/payment counts |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/verify-customer-otp` | Complete delivery |
| POST | `/api/v1/delivery/deliveries/{deliveryId}/cancel` | Cancel delivery with customer OTP |
| GET | `/api/v1/delivery/deliveries/{deliveryId}/completed-detail` | Completed receipt/detail |
| GET | `/api/v1/delivery/deliveries/history?period=&page=&limit=` | Delivery history |
| GET | `/api/v1/delivery/driver/profile` | Driver profile |
| PATCH | `/api/v1/delivery/driver/status` | Duty on/off |
| GET | `/api/v1/delivery/driver/inventory` | Current van inventory |
| GET | `/api/v1/delivery/notifications` | Driver notification list |
| GET | `/api/v1/delivery/notifications/unread-count` | Bell badge |
| GET | `/api/v1/delivery/notifications/{notificationId}` | Notification detail |
| PATCH | `/api/v1/delivery/notifications/{notificationId}/read` | Mark one read |
| POST | `/api/v1/delivery/notifications/read-all` | Mark all read |

## 1. Place an order

Customer app:

```http
POST /api/v1/customer/orders
```

Merchant app, on behalf of a customer:

```http
POST /api/v1/merchant/orders
```

Customer and merchant calls use the same order body. `customerId` must be the logged-in customer
for the Customer App; Merchant App may use any eligible customer belonging to that merchant.

```json
{
  "customerId": "customer-uuid",
  "items": [
    {"cylinderType": "LPG_19KG", "quantity": 2}
  ],
  "orderMode": "NEW",
  "deliverySiteId": null
}
```

For an industrial customer, `deliverySiteId` is required. Do not send `source` from the app; the
backend derives `CUSTOMER_APP` or `MERCHANT_APP` from the authenticated channel.

Important response fields used by all apps:

```json
{
  "id": "order-uuid",
  "orderNumber": "ORD-2610-0042",
  "customerId": "customer-uuid",
  "items": [],
  "totalCylinders": 2,
  "totalAmount": 3200,
  "status": "PLACED",
  "statusHistory": [],
  "cutoff": {
    "cutoffTime": "15:00",
    "withinCutoff": true,
    "scheduledDeliveryDate": "2026-10-06",
    "message": "..."
  },
  "deliverySlipId": null,
  "invoiceId": null
}
```

Result: order status is `PLACED`. The customer gets `ORDER_PLACED`; merchant staff get
`ORDER_RECEIVED`.

Related order payloads:

```jsonc
// POST /orders/quote
{
  "customerId": "customer-uuid",
  "items": [{"cylinderType": "LPG_19KG", "quantity": 2}]
}
```

```jsonc
// POST /orders/{orderId}/cancel (body is optional)
{"reason": "Customer changed requirement"}
```

```jsonc
// Merchant POST /orders/repeat
{
  "customerId": "customer-uuid",
  "items": null,
  "deliverySiteId": null
}
```

Customer `POST /orders/repeat` may send no body. Reorder POST bodies may optionally override
`items` and `deliverySiteId`; always use the GET preview first because current price or
availability may differ from the old order.

## 2. Confirm and assign one order

Load crew pickers first:

```http
GET /api/v1/merchant/delivery-users/available?delivery_user_type=DRIVER
GET /api/v1/merchant/delivery-users/available?delivery_user_type=HELPER
```

Use the returned user's `userId` as `driverUserId`/`helperUserId`. Do not send a delivery-profile
id in these fields.

```http
POST /api/v1/merchant/orders/{orderId}/confirm
Permission: orders.update
```

```json
{
  "delivery": {
    "vehicleNumber": "MP09 GH 4521",
    "driverUserId": "driver-user-uuid",
    "helperUserId": "helper-user-uuid",
    "deliveryDate": "2026-10-06"
  }
}
```

`driverUserId` is required for the normal Delivery App flow: it routes the assignment notification
and is how the driver is authorized to open/start the slip. The backend still accepts
`driverName` for a legacy/hired-driver record, but that person cannot operate the authenticated
Delivery App, so new mobile flows must use `driverUserId`. `helperUserId`, `helperName`, and
`deliveryDate` are optional; the date defaults to the order's cutoff-derived delivery date.

Result:

- order becomes `CONFIRMED`;
- a delivery slip is created in the same transaction;
- the order response contains `deliverySlipId`;
- customer gets `ORDER_CONFIRMED`;
- assigned driver gets `DELIVERY_ASSIGNED`.

The full operation is atomic. If crew validation or slip creation fails, the order is not left
confirmed without an assignment. Retrying the same confirmed order is idempotent.

## 3. Confirm and assign orders in bulk

```http
POST /api/v1/merchant/orders/confirm
Permission: orders.update
```

```json
{
  "orderIds": ["order-uuid-1", "order-uuid-2"],
  "delivery": {
    "vehicleNumber": "MP09 GH 4521",
    "driverUserId": "driver-user-uuid",
    "helperUserId": "helper-user-uuid",
    "deliveryDate": "2026-10-06"
  }
}
```

Example response:

```json
{
  "confirmed": 2,
  "orders": [
    {"id": "order-uuid-1", "status": "CONFIRMED", "deliverySlipId": "slip-uuid-1"},
    {"id": "order-uuid-2", "status": "CONFIRMED", "deliverySlipId": "slip-uuid-2"}
  ]
}
```

The response orders contain the normal full order representation. The operation is all-or-
nothing. One driver/helper can hold multiple slips when they are on the same vehicle and date;
an assignment to a different live vehicle/date is rejected as a conflict.

Use this endpoint for a delivery round. Do not call single confirm repeatedly from the UI.

## 4. Driver starts delivery

Single:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/out-for-delivery
Permission: deliveries.update_status
```

Bulk (also valid with one id):

```http
POST /api/v1/delivery/deliveries/out-for-delivery
Permission: deliveries.update_status
```

```json
{
  "deliveryIds": ["slip-uuid-1", "slip-uuid-2"]
}
```

Result for every slip:

- slip becomes `DISPATCHED`;
- order becomes `OUT_FOR_DELIVERY`;
- stock availability is checked for the whole round;
- customer gets `DELIVERY_DISPATCHED`, including the OTP;
- `startedAt` is recorded for the driver.

The bulk operation is all-or-nothing. A driver cannot start another driver's slip. In local and
staging environments the response may contain `devConfirmationCode`; it is always `null` in
production.

Single response is one object; bulk response is a list of the same object:

```json
{
  "deliveryId": "slip-uuid-1",
  "orderNumber": "ORD-2610-0042",
  "status": "out_for_delivery",
  "updatedAt": "2026-10-05T12:00:00Z",
  "devConfirmationCode": null
}
```

## 4A. Driver reaches the customer location

When the driver taps **I am on location**, call:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/verify-location
Permission: deliveries.update_status
```

```json
{"latitude": 22.7196, "longitude": 75.8577}
```

Example response:

```json
{
  "deliveryId": "slip-uuid-1",
  "deliveryStatus": "ON_LOCATION",
  "orderStatus": "ON_LOCATION",
  "arrivedAt": "2026-10-05T12:20:00Z",
  "isAtLocation": true,
  "distanceMetersFromDestination": 42.5,
  "isLocationCaptured": true,
  "message": "Location verified successfully"
}
```

This action is idempotent. On the first click:

- delivery slip becomes `ON_LOCATION`;
- order becomes `ON_LOCATION` and gets a status-history entry;
- Delivery App queue returns `status: "on_location"`;
- Merchant delivery board returns `status: "ON_LOCATION"`;
- Customer order detail/list returns `status: "ON_LOCATION"`;
- customer gets `DELIVERY_ON_LOCATION_CUSTOMER`;
- merchant gets `DELIVERY_ON_LOCATION_MERCHANT`.

If destination coordinates exist, `isAtLocation` and `distanceMetersFromDestination` tell the
app whether the GPS fix is inside the 200-metre radius. Missing/inaccurate GPS does not block the
workflow. Retrying the action updates the captured coordinates without duplicating history or
notifications.

## 5. Complete delivery with customer OTP

First record the delivered/empty/payment counts:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/confirm
```

```json
{
  "deliveredItems": [
    {"cylinderType": "LPG_19KG", "quantity": 2}
  ],
  "collectedEmpties": [
    {"cylinderType": "LPG_19KG", "quantity": 2}
  ],
  "payment": {
    "method": "cash",
    "split": "full",
    "amountCollected": 3200,
    "payableAmount": 3200,
    "pendingBalance": 0
  },
  "driverNotes": "Delivered at gate"
}
```

Counts response:

```json
{
  "deliveryId": "slip-uuid-1",
  "customerOtpRequired": true,
  "otpChannel": "IN_APP_NOTIFICATION",
  "message": "OTP has been sent to customer's app notification"
}
```

Then verify the OTP given by the customer:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/verify-customer-otp
```

```json
{"otp": "1234"}
```

Successful OTP response includes `deliveryId`, `orderNumber`, `status: "completed"`,
`completedAt`, delivered items, empty-return totals, pending empty dues, and payment summary.

Only the OTP call completes the handover. It moves the slip to `DELIVERED`, the order to
`DELIVERED`, updates stock, raises the invoice, and sends `DELIVERY_COMPLETED` plus the invoice
notification to the customer.

## 6. Cancel a delivery with customer OTP

```http
POST /api/v1/delivery/deliveries/{deliveryId}/cancel
Permission: deliveries.update_status
```

```json
{
  "otp": "1234",
  "reason": "Customer refused delivery"
}
```

Example response:

```json
{
  "deliveryId": "slip-uuid-1",
  "orderNumber": "ORD-2610-0042",
  "deliveryStatus": "FAILED",
  "orderStatus": "CANCELLED",
  "cancelledAt": "2026-10-05T12:30:00Z"
}
```

The OTP must be the code created when this trip went out for delivery. A wrong code changes
nothing. On success:

- slip becomes `FAILED`;
- order becomes `CANCELLED`;
- confirmation code is invalidated;
- customer gets `ORDER_CANCELLED`;
- merchant gets `DELIVERY_FAILED`;
- the assigned driver gets `DELIVERY_UNASSIGNED`.

There is no reschedule. A fresh attempt requires a new order.

## 7. Other Delivery App request bodies

The `verify-location` endpoint is the **I am on location** status action documented in section
4A. The other Delivery App utility payloads are:

Update items before handover:

```http
PUT /api/v1/delivery/deliveries/{deliveryId}/update-items
```

```json
{
  "updatedItems": [
    {"cylinderType": "LPG_19KG", "quantity": 2}
  ],
  "reason": "Customer accepted reduced quantity"
}
```

Generate payment QR:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/generate-qr
```

```json
{"amount": 3200, "paymentSplit": "full"}
```

Set driver duty state:

```http
PATCH /api/v1/delivery/driver/status
```

```json
{"onDuty": true}
```

The backend refuses `onDuty: false` while that driver still has dispatched deliveries.

## Notification contract

| Event | Recipient | When | App action on tap |
|---|---|---|---|
| `ORDER_PLACED` | Customer | Customer/merchant places order | Open order detail |
| `ORDER_RECEIVED` | Merchant | New order arrives | Open order detail/confirmation |
| `ORDER_CONFIRMED` | Customer | Merchant confirms and assigns | Open order tracking |
| `DELIVERY_ASSIGNED` | Driver | Slip is assigned | Open assigned delivery |
| `DELIVERY_DISPATCHED` | Customer | Driver starts trip | Open tracking; show OTP to customer |
| `DELIVERY_ON_LOCATION_CUSTOMER` | Customer | Driver taps I am on location | Open order tracking |
| `DELIVERY_ON_LOCATION_MERCHANT` | Merchant | Driver taps I am on location | Open order/delivery detail |
| `DELIVERY_COMPLETED` | Customer | Customer OTP completes handover | Open completed order |
| `INVOICE_RAISED` | Customer | Delivery completes | Open invoice/payment detail |
| `ORDER_CANCELLED` | Customer | Order/delivery is cancelled | Open cancelled order |
| `ORDER_CANCELLED_MERCHANT` | Merchant | Pre-trip order cancellation | Remove from active work queue |
| `DELIVERY_FAILED` | Merchant | Driver cancels failed delivery | Open failed slip/order |
| `DELIVERY_UNASSIGNED` | Driver | Failed delivery closes assignment | Remove from active queue |

The four-digit delivery OTP is carried in the customer's `DELIVERY_DISPATCHED` notification.
Production apps must never depend on `devConfirmationCode`; that field is only populated in
local/staging configurations.

Notification row wire shape:

```json
{
  "id": "notification-uuid",
  "title": "Order out for delivery",
  "message": "Order ORD-2610-0042 has left the godown. Share code 1234 with the driver.",
  "severity": "INFO",
  "category": "ORDER",
  "createdAt": "2026-10-05T12:00:00Z",
  "read": false,
  "referenceType": "ORDER",
  "referenceId": "order-uuid"
}
```

## Frontend changes required

### Customer App team

1. Keep order placement on `POST /customer/orders`; send `customerId` of the logged-in customer.
2. Build tracking from `status` and `statusHistory`. Supported live order states are `PLACED`,
   `CONFIRMED`, `OUT_FOR_DELIVERY`, `ON_LOCATION`, `DELIVERED`, and `CANCELLED`.
3. Show Cancel only for `PLACED` or `CONFIRMED`. Hide it from `OUT_FOR_DELIVERY` onward.
4. On `DELIVERY_DISPATCHED`, prominently show the OTP and tell the customer to share it only
   after accepting the delivery or acknowledging cancellation.
5. Refresh order detail after `ORDER_CONFIRMED`, `DELIVERY_DISPATCHED`,
   `DELIVERY_ON_LOCATION_CUSTOMER`, `DELIVERY_COMPLETED`, or `ORDER_CANCELLED`.
6. Do not add confirm, assignment, dispatch, reschedule, delivered, or delivery-failure buttons.

### Merchant App team

1. Keep both customer-originated and merchant-originated orders in the same order list.
2. Replace the old Confirm button with a Confirm & Assign sheet. Required UI fields: driver and
   vehicle. Optional: helper and delivery date.
3. For bulk assignment, allow selecting up to 50 `PLACED` orders and call
   `POST /merchant/orders/confirm` once. Use the returned `deliverySlipId` from every order.
4. Treat single/bulk confirmation as all-or-nothing. On an error, refresh the list and show the
   backend message; do not mark some selected cards locally.
5. Remove Schedule Delivery and Reschedule actions/screens.
6. Remove merchant Dispatch, Confirm Delivery, and Fail Delivery buttons. These operations now
   belong only to the Delivery App.
7. Keep the merchant delivery board as list/detail read-only screens.
8. Show `ON_LOCATION` on the order and delivery board, and refresh after
   `DELIVERY_ON_LOCATION_MERCHANT`.
9. Show `DELIVERY_FAILED` and `ORDER_CANCELLED_MERCHANT` notifications to operations staff.

### Delivery App team

1. Build the active queue from `GET /delivery/deliveries/today` and assigned-delivery
   notifications.
2. Use the bulk out-for-delivery endpoint for a van round; it also supports a one-id list. Keep
   the single endpoint for a one-card action if useful.
3. If bulk start fails, keep the whole selected round unchanged and show the backend error.
4. After starting, refresh the queue/inventory and show state `out_for_delivery`.
5. Add an **I am on location** button after `out_for_delivery`. Send the current latitude and
   longitude to `/verify-location`, then show state `on_location`.
6. Successful handover is a two-request flow: send counts to `/confirm`, then submit customer OTP
   to `/verify-customer-otp`. Do not show Completed after the first request.
7. Failed/refused delivery uses `/cancel` with OTP and reason. Do not call an old `/fail` route.
8. After successful cancel, remove the card from active queue and show it in history as failed;
   its order is final `CANCELLED` and cannot be rescheduled.
9. Handle wrong OTP as a recoverable validation error and keep the delivery active.

## Backend changes delivered

- Confirmation and delivery assignment are now one atomic transaction.
- Added single confirm-and-assign payload and bulk confirm-and-assign endpoint.
- Added support for several orders on the same driver's vehicle/date round.
- Driver out-for-delivery now performs the real slip/order transition, stock check, OTP creation,
  and customer notification.
- Added bulk out-for-delivery with all-or-nothing behavior.
- Added `ON_LOCATION` order/slip status to the existing location endpoint, including idempotent
  history and Customer/Merchant notifications.
- Added driver delivery cancellation with customer OTP.
- Failed delivery now makes slip `FAILED` and order `CANCELLED`; rescheduling was removed.
- Added/updated customer, merchant, and driver notifications for the lifecycle.
- Merchant delivery writes were removed; merchant delivery list/detail remain read-only.
- Payment/invoice tests and flows now complete delivery through the Delivery App contract.
- No database migration is required for this release.

## Release coordination

This is a breaking API change for old Merchant and Delivery App builds because merchant delivery
write endpoints no longer exist.

Recommended rollout:

1. Deploy backend.
2. Release Merchant App with Confirm & Assign and without Schedule/Dispatch/Fail actions.
3. Release Delivery App with single/bulk out-for-delivery and OTP cancel.
4. Release Customer App notification/tracking updates.
5. Verify push/device registration for all three Firebase/app channels before production smoke
   testing.

Production smoke test:

1. Place one customer order and one merchant-created order.
2. Confirm/assign them together to one driver.
3. Confirm both appear in the driver's queue and two assignment notifications exist.
4. Start both through bulk out-for-delivery; verify each customer receives their own OTP.
5. Deliver one with OTP and cancel the other with OTP.
6. Verify final order states are `DELIVERED` and `CANCELLED`, merchant board states are
   `DELIVERED` and `FAILED`, stock/invoice changed only for the delivered order, and all required
   notifications appeared.

## Merchant delivery board

The merchant delivery board is read-only:

```http
GET /api/v1/merchant/deliveries
GET /api/v1/merchant/deliveries/{deliveryId}
```

The following old merchant writes have been removed:

```text
POST /api/v1/merchant/deliveries
POST /api/v1/merchant/deliveries/{deliveryId}/dispatch
POST /api/v1/merchant/deliveries/{deliveryId}/confirm
POST /api/v1/merchant/deliveries/{deliveryId}/fail
```

Their responsibilities now belong to confirm-and-assign or the authenticated delivery app.

| Old app action | New implementation |
|---|---|
| Confirm order, then open Schedule Delivery | One `POST /merchant/orders/{orderId}/confirm` with `delivery` |
| Schedule several orders separately | One `POST /merchant/orders/confirm` bulk call |
| Merchant Dispatch | Driver single/bulk out-for-delivery |
| Merchant Confirm Delivery | Driver `/confirm`, then `/verify-customer-otp` |
| Merchant Fail Delivery | Driver `/cancel` with customer OTP and reason |
| Reschedule failed delivery | Removed; create a new order |

## Important error behavior

- `404 DELIVERY_NOT_FOUND`: slip does not exist, belongs to another merchant/driver, or is not
  assigned to the signed-in driver.
- `409 ORDER_ALREADY_CANCELLED`: a stale driver attempts to start a cancelled order.
- `409 DELIVERY_ALREADY_SETTLED`: delivered/failed slip is acted on again.
- `409 DELIVERY_NOT_READY`: action requires a dispatched slip.
- `409 DELIVERY_ALREADY_EXISTS`: order already has a live slip.
- `422 VALIDATION_ERROR` with `driver_already_assigned`/`helper_already_assigned`: crew is
  committed to a different vehicle/date round.
- `422 VALIDATION_ERROR` with `incorrect_otp`: malformed or incorrect customer OTP.
- `422` validation error: empty id lists, more than 50 ids, or invalid body fields.

Both bulk operations accept at most 50 ids and deduplicate repeated ids.
