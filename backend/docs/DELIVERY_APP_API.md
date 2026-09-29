# MBGA Delivery App - Backend API

Everything the delivery app can call. Generated from the running server, so this document and the API cannot disagree.

Regenerate with `python scripts/generate_delivery_api_docs.py`. Live, browsable version: **`{BASE_URL}/docs/delivery`**.


## Base URL

```
{BASE_URL}/api/v1/delivery
```

The `/delivery` segment is what makes a request a driver request. A token issued on this channel is rejected on `/merchant`, `/customer` and `/admin`, and theirs are rejected here.


## Headers

| Header | Value | When |
|---|---|---|
| `Authorization` | `Bearer <accessToken>` | Every endpoint except the OTP ones |
| `Content-Type` | `application/json` | Every request with a body |


## Errors

Every failure comes back in one shape:

```json
{
  "detail": {
    "code": "DELIVERY_NOT_READY",
    "message": "Order MBGA-R-0007 has not been dispatched yet...",
    "fields": [],
    "request_id": "0f3c9a1e-..."
  }
}
```

Show `message` to the driver and branch on `code` - never on the message text, which is written for people and will be reworded. Quote `request_id` when reporting a bug; it finds the exact request in the server logs.


> **If your HTTP client expects `{ "success": ..., "error": ... }`** - the shape in the original integration spec - say so and the server can be switched to it for this channel. It is one deployment flag (`DELIVERY_RESPONSE_ENVELOPE`). It is **off** today because turning it on also wraps the auth responses you are already parsing.


---

## The delivery flow

The order the calls have to happen in. This is the part the endpoint list cannot tell you, and getting it wrong is the difference between stock that reconciles and stock that does not.

```
1.  GET  /deliveries/today                      what am I delivering
2.  POST /deliveries/{id}/start                 I have set off (sends my location)
3.  POST /deliveries/{id}/confirm               what I counted at the gate
4.  POST /deliveries/{id}/verify-customer-otp   the customer's code -> DONE
```

**Step 3 does not complete the delivery.** It records the counts and nothing else: no stock moves, the order does not advance, the customer is not told. It exists so the app can be backgrounded between counting cylinders and the customer finding their code without losing what the driver entered. Safe to call again.

**Step 4 is the delivery.** Only here do the cylinders come off the merchant's books, the order become `DELIVERED`, and the customer get their notification. Until it succeeds, nothing has happened.


### Where the customer's code comes from

It is **not** sent by SMS when the driver confirms. It is generated when the office dispatches the van, and it reaches the customer inside their own app's "out for delivery" notification. The customer therefore has it before the driver arrives, and neither of them needs a signal at the gate.

A wrong code returns `422` and costs one attempt out of ten. After ten the slip can only be closed from the office, so show the driver how many tries are left rather than letting them exhaust it.


### Statuses the app will see

| `status` | Meaning |
|---|---|
| `pending` | Assigned to this driver - either not dispatched yet, or dispatched and not started. |
| `in_progress` | The driver has pressed Start. |
| `completed` | Handed over and confirmed. |
| `failed` | Closed without delivering. Only the office can set this. |

### Errors worth handling by name

| `code` | HTTP | What happened |
|---|---|---|
| `DELIVERY_NOT_FOUND` | 404 | Not this driver's delivery. Never 403 - ids are guessable, so the server will not confirm one exists. |
| `DELIVERY_NOT_READY` | 409 | The office has not dispatched the van. Nothing has left the godown yet. |
| `DELIVERY_ALREADY_SETTLED` | 409 | Already delivered or failed. |
| `DELIVERY_PARTIAL_NOT_SUPPORTED` | 422 | `deliveredQuantity` must equal `cylindersAllocated`. A part delivery is an office decision - they close this slip and raise a new one. |
| `DELIVERY_EMPTIES_EXCEED_LOAD` | 422 | More empties than cylinders on the slip. |
| `DELIVERY_CODE_LOCKED` | 409 | Ten wrong codes. The office has to close it. |
| `DRIVER_HAS_ACTIVE_DELIVERIES` | 409 | Cannot go off duty with a van still out. |


---

## Authentication

Sign-in is by OTP on the driver's registered mobile. A token minted here works only on the delivery channel - it is refused by the merchant and customer APIs, and theirs are refused here.


### `POST /auth/logout`

**Logout**

Revokes the session of the given refresh token. Always returns 204, even when nothing was revoked.


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `refresh_token` | string · nullable | no |  |
| `device_id` | string · nullable | no | Ignored. |


**Error statuses**: `422`


### `POST /auth/logout-all`

**Logout All**


**Error statuses**: `401`, `403`


### `GET /auth/me`

**Me**


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `user_id` | string | yes |  |
| `login_channel` | LoginChannel | yes |  |
| `user_type` | string | yes | CUSTOMER, DELIVERY_PARTNER, MERCHANT_STAFF or ADMIN. |
| `session_type` | string | yes | `access` (full app session) or `onboarding` (customer registration only). |
| `role` | string · nullable | no | Primary role code for this app, e.g. manager, driver, customer. |
| `active_roles` | string[] | no | Distinct role codes allowed on this app. |
| `account_status` | string | yes |  |
| `approval_status` | string · nullable | no | Merchant, delivery-profile or customer approval state. |
| `profile_completion_status` | string · nullable | no | Customer only: NOT_STARTED, INCOMPLETE or COMPLETE. |
| `next_action` | NextAction | yes |  |
| `merchant` | MerchantSummary · nullable | no | Merchant and delivery apps only. |
| `delivery_profile` | DeliveryProfileSummary · nullable | no | Delivery app only. |
| `customer_profile` | CustomerProfileSummary · nullable | no | Customer app only, once details are submitted. |
| `display_name` | string · nullable | no |  |
| `mobile_number` | string · nullable | no |  |
| `country_code` | string · nullable | no |  |
| `effective_permissions` | string[] | no |  |
| `status` | string | yes | Deprecated: same value as account_status. |
| `profile` | DeliveryProfileSummary · nullable | no | Deprecated: use delivery_profile or customer_profile. |


**Error statuses**: `401`, `403`


### `POST /auth/otp/request`

**Request Otp**


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `mobile_number` | string | yes | Max 15 characters. |
| `country_code` | string | no | Defaults to `"+91"`. Max 5 characters. |
| `login_channel` | LoginChannel | no | Ignored: the app channel is taken from the URL. Accepts the name or the numeric code (1 CUSTOMER, 2 DELIVERY, 3 MERCHANT, 4 ADMIN). Defaults to `"CUSTOMER"`. |
| `device` | DeviceInfo · nullable | no |  |


**Error statuses**: `403`, `404`, `422`, `429`


### `POST /auth/otp/resend`

**Resend Otp**


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_id` | string | yes | Max 36 characters. |
| `device` | DeviceInfo · nullable | no |  |


**Error statuses**: `400`, `403`, `404`, `422`, `429`


### `POST /auth/otp/verify`

**Verify Otp**


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_id` | string | yes | Max 36 characters. |
| `mobile_number` | string · nullable | no | Ignored. |
| `country_code` | string | no | Ignored. Defaults to `"+91"`. Max 5 characters. |
| `login_channel` | LoginChannel | no | Ignored. Accepts the name or the numeric code (1 CUSTOMER, 2 DELIVERY, 3 MERCHANT, 4 ADMIN). Defaults to `"CUSTOMER"`. |
| `otp` | string | yes | Numeric code with OTP_LENGTH digits (4 in the current configuration). |
| `device` | DeviceInfo · nullable | no |  |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `user_id` | string | yes |  |
| `login_channel` | LoginChannel | yes |  |
| `user_type` | string | yes | CUSTOMER, DELIVERY_PARTNER, MERCHANT_STAFF or ADMIN. |
| `session_type` | string | yes | `access` (full app session) or `onboarding` (customer registration only). |
| `role` | string · nullable | no | Primary role code for this app, e.g. manager, driver, customer. |
| `active_roles` | string[] | no | Distinct role codes allowed on this app. |
| `account_status` | string | yes |  |
| `approval_status` | string · nullable | no | Merchant, delivery-profile or customer approval state. |
| `profile_completion_status` | string · nullable | no | Customer only: NOT_STARTED, INCOMPLETE or COMPLETE. |
| `next_action` | NextAction | yes |  |
| `merchant` | MerchantSummary · nullable | no | Merchant and delivery apps only. |
| `delivery_profile` | DeliveryProfileSummary · nullable | no | Delivery app only. |
| `customer_profile` | CustomerProfileSummary · nullable | no | Customer app only, once details are submitted. |
| `token` | TokenPair | yes |  |
| `is_new_user` | bool | no | True when this verification created the account. Defaults to `false`. |
| `code` | string | no | Defaults to `"OTP_VERIFIED"`. |
| `message` | string | no | Defaults to `"OTP verified"`. |


**Error statuses**: `400`, `403`, `404`, `422`


### `POST /auth/token/refresh`

**Refresh Token**


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `refresh_token` | string | yes |  |
| `device_id` | string · nullable | no | Deprecated: use device.device_id. |
| `device` | DeviceInfo · nullable | no | Send when the push token or app version changed; omitted values are kept. |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `access_token` | string | yes |  |
| `refresh_token` | string | yes |  |
| `token_type` | TokenType | no | Defaults to `"Bearer"`. |
| `expires_in` | int | yes | Access-token lifetime in seconds. |


**Error statuses**: `401`, `403`, `422`


---

## Deliveries

The driver's work. Every one of these is scoped to the slips addressed to **this** driver; another driver's delivery returns `404`, never `403`.


### `GET /deliveries`

**My deliveries**

Every slip addressed to this driver, newest first.


**Query parameters**

| Name | Type | Required | Notes |
|---|---|---|---|
| `scheduledDate` | string · nullable | no | Limit to one delivery day. |
| `limit` | int | no |  |


**Response** - an array of:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `orderNumber` | string | yes |  |
| `slipNumber` | string | yes |  |
| `customerName` | string | yes |  |
| `customerPhone` | string · nullable | no |  |
| `address` | string | yes |  |
| `deliverySiteName` | string | yes |  |
| `items` | app__modules__driver__schemas__DeliveryItemResponse[] | yes |  |
| `itemsSummary` | string | yes |  |
| `cylindersAllocated` | int | yes |  |
| `status` | DriverDeliveryStatus | yes |  |
| `scheduledDate` | string | yes |  |
| `distanceKm` | float · nullable | no |  |
| `startedAt` | string · nullable | no |  |
| `completedAt` | string · nullable | no |  |
| `emptiesCollected` | int | yes |  |
| `requiresCustomerOtp` | bool | yes |  |


**Error statuses**: `401`, `403`, `422`


### `GET /deliveries/history`

**Completed deliveries**

What this driver has already settled - delivered or failed (§6.4).


**Query parameters**

| Name | Type | Required | Notes |
|---|---|---|---|
| `limit` | int | no |  |


**Response** - an array of:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `orderNumber` | string | yes |  |
| `slipNumber` | string | yes |  |
| `customerName` | string | yes |  |
| `customerPhone` | string · nullable | no |  |
| `address` | string | yes |  |
| `deliverySiteName` | string | yes |  |
| `items` | app__modules__driver__schemas__DeliveryItemResponse[] | yes |  |
| `itemsSummary` | string | yes |  |
| `cylindersAllocated` | int | yes |  |
| `status` | DriverDeliveryStatus | yes |  |
| `scheduledDate` | string | yes |  |
| `distanceKm` | float · nullable | no |  |
| `startedAt` | string · nullable | no |  |
| `completedAt` | string · nullable | no |  |
| `emptiesCollected` | int | yes |  |
| `requiresCustomerOtp` | bool | yes |  |


**Error statuses**: `401`, `403`, `422`


### `GET /deliveries/today`

**Today's deliveries**

The driver's queue for today (§6.1).

Today is read on the **IST business calendar**, not UTC: a slip scheduled for the 28th
belongs to the 28th in the godown, and a driver opening the app at 06:00 IST must not still
be looking at yesterday's list.

Ordered as work: what is on the van, then what is still to load, then what is done.


**Response** - an array of:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `orderNumber` | string | yes |  |
| `slipNumber` | string | yes |  |
| `customerName` | string | yes |  |
| `customerPhone` | string · nullable | no |  |
| `address` | string | yes |  |
| `deliverySiteName` | string | yes |  |
| `items` | app__modules__driver__schemas__DeliveryItemResponse[] | yes |  |
| `itemsSummary` | string | yes |  |
| `cylindersAllocated` | int | yes |  |
| `status` | DriverDeliveryStatus | yes |  |
| `scheduledDate` | string | yes |  |
| `distanceKm` | float · nullable | no |  |
| `startedAt` | string · nullable | no |  |
| `completedAt` | string · nullable | no |  |
| `emptiesCollected` | int | yes |  |
| `requiresCustomerOtp` | bool | yes |  |


**Error statuses**: `401`, `403`


### `GET /deliveries/{deliveryId}`

**Delivery detail**

One drop. Another driver's delivery is a 404, never a 403.


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `orderNumber` | string | yes |  |
| `slipNumber` | string | yes |  |
| `customerName` | string | yes |  |
| `customerPhone` | string · nullable | no |  |
| `address` | string | yes |  |
| `deliverySiteName` | string | yes |  |
| `items` | app__modules__driver__schemas__DeliveryItemResponse[] | yes |  |
| `itemsSummary` | string | yes |  |
| `cylindersAllocated` | int | yes |  |
| `status` | DriverDeliveryStatus | yes |  |
| `scheduledDate` | string | yes |  |
| `distanceKm` | float · nullable | no |  |
| `startedAt` | string · nullable | no |  |
| `completedAt` | string · nullable | no |  |
| `emptiesCollected` | int | yes |  |
| `requiresCustomerOtp` | bool | yes |  |


**Error statuses**: `401`, `403`, `404`, `422`


### `POST /deliveries/{deliveryId}/confirm`

**Record the counts**

What the driver counted at the gate (§7.2).

**This does not complete the delivery.** No stock moves, the order does not advance and the
customer is not told - that happens at `verify-customer-otp`. Saving the counts separately is
what lets the app be backgrounded between counting cylinders and the customer finding their
code.

A part delivery is refused with `422`: the ledger books the slip's whole load at handover, so
accepting a smaller number would take the full quantity off the shelf while the driver still
had some on the van.


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `deliveredQuantity` | int | yes |  |
| `emptyCollectedQuantity` | int | no | Defaults to `0`. |
| `note` | string · nullable | no |  |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `deliveryId` | string | yes |  |
| `customerOtpRequired` | bool | yes |  |
| `deliveredQuantity` | int | yes |  |
| `emptyCollectedQuantity` | int | yes |  |


**Error statuses**: `401`, `403`, `404`, `409`, `422`


### `POST /deliveries/{deliveryId}/start`

**Start the trip**

Record that the driver has set off, and where from (§7.1).

`isAtLocation` is a hint for the UI, not a gate: it is true whenever the distance cannot be
measured, because most delivery sites have no recorded coordinates and a driver standing at
the gate must still be able to work. Pressing Start twice is safe - the first departure time
is kept and the position refreshed.


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `latitude` | float | yes |  |
| `longitude` | float | yes |  |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `deliveryId` | string | yes |  |
| `isAtLocation` | bool | yes |  |
| `distanceMetersFromDestination` | float · nullable | no |  |
| `status` | DriverDeliveryStatus | yes |  |


**Error statuses**: `401`, `403`, `404`, `409`, `422`


### `POST /deliveries/{deliveryId}/verify-customer-otp`

**Verify the customer's code**

Complete the handover (§7.3).

The customer reads out the four-digit code their "out for delivery" notification carried.
This runs the **same** confirm the office runs: stock comes off the books, the order becomes
DELIVERED and the customer is notified.

A wrong code costs one attempt out of a generous budget - a misheard digit at a noisy gate is
the common case, and a locked slip means a wasted trip.


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `otp` | string | yes | Max 10 characters. |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `deliveryId` | string | yes |  |
| `orderNumber` | string | yes |  |
| `deliveredQuantity` | int | yes |  |
| `emptyCollectedQuantity` | int | yes |  |
| `completedAt` | string | yes |  |


**Error statuses**: `401`, `403`, `404`, `409`, `422`


---

## Driver

The driver's own record, and what their van is carrying.


### `GET /driver/inventory`

**What is on my van**

Computed from this driver's dispatched slips, never stored (§10).

A van-stock table would be a second place the same cylinders are counted, and it would drift
the first time a delivery was confirmed from the office rather than the app.


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `fullCylinders` | DriverInventoryLine[] | yes |  |
| `fullCylinderCount` | int | yes |  |
| `emptyCylinderCount` | int | yes |  |
| `activeDeliveries` | int | yes |  |


**Error statuses**: `401`, `403`


### `GET /driver/profile`

**My profile**

The driver's own record (§8.1).


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `name` | string | yes |  |
| `phone` | string | yes |  |
| `employeeCode` | string · nullable | no |  |
| `vehicleNumber` | string · nullable | no |  |
| `role` | string | yes |  |
| `onDuty` | bool | yes |  |
| `avatarInitials` | string · nullable | no |  |


**Error statuses**: `401`, `403`


### `PATCH /driver/status`

**Go on or off duty**

The driver's own shift switch (§8.2).

Going off duty is refused with `409` while a van of theirs is still out: those cylinders are
on the road under this driver's name, and signing off would leave a dispatched slip with
nobody responsible for it.


**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `onDuty` | bool | yes |  |


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `name` | string | yes |  |
| `phone` | string | yes |  |
| `employeeCode` | string · nullable | no |  |
| `vehicleNumber` | string · nullable | no |  |
| `role` | string | yes |  |
| `onDuty` | bool | yes |  |
| `avatarInitials` | string · nullable | no |  |


**Error statuses**: `401`, `403`, `404`, `409`, `422`


---

## Notifications

The in-app bell. A driver sees only what is addressed to them personally - never the merchant's shared notifications.


### `GET /notifications`

**Notifications**

Newest first.

A customer sees their own; staff see their merchant's, shared across the team
(spec §15). `read` is per user, so one person opening a notification does not hide
it from the rest.


**Query parameters**

| Name | Type | Required | Notes |
|---|---|---|---|
| `unreadOnly` | bool | no | Only the ones not yet read. |


**Response** - an array of:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `message` | string | yes |  |
| `severity` | Severity | yes |  |
| `category` | Category | yes |  |
| `createdAt` | string | yes |  |
| `read` | bool | yes |  |
| `referenceType` | ReferenceType · nullable | no |  |
| `referenceId` | string · nullable | no |  |


**Error statuses**: `401`, `403`, `422`


### `POST /notifications/read-all`

**Mark all read**


**Error statuses**: `401`, `403`


### `GET /notifications/unread-count`

**Unread count**

The bell badge, without fetching the list to count it.


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `unread` | int | yes |  |


**Error statuses**: `401`, `403`


### `GET /notifications/{notificationId}`

**Notification detail**

Someone else's notification is reported as 404, never 403.


**Response**

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `message` | string | yes |  |
| `severity` | Severity | yes |  |
| `category` | Category | yes |  |
| `createdAt` | string | yes |  |
| `read` | bool | yes |  |
| `referenceType` | ReferenceType · nullable | no |  |
| `referenceId` | string · nullable | no |  |


**Error statuses**: `401`, `403`, `404`, `422`


### `PATCH /notifications/{notificationId}/read`

**Mark read (PATCH)**

The same write under the verb the delivery app calls.

The merchant and customer apps already ship against `POST`, and the delivery app against
`PATCH`. Marking something read is a bodyless state change, so neither verb is wrong -
and breaking a shipped app to settle the question would be.


**Error statuses**: `401`, `403`, `404`, `422`


### `POST /notifications/{notificationId}/read`

**Mark read**

Idempotent - marking an already-read notification read again is not an error.


**Error statuses**: `401`, `403`, `404`, `422`

