# MBGA Commercial LPG Platform — Backend API Specification

> **Audience:** backend team building the real API for the Customer app and the Merchant app.
> **Source of truth for shapes:** `<app>/src/shared/types/*.ts` (every field below maps 1:1 to those TypeScript types; identical copy in `customer-app/` and `merchant-app/`).
> **Current state:** every endpoint is implemented as an in-memory mock in `<app>/src/shared/services/*Service.ts`.
> The frontend swaps mock → real per service function (see `API_INTEGRATION.md`) — **screens never change**.
>
> Paths and HTTP methods below are **proposals** the frontend will adopt; if the backend prefers other paths,
> only the service files change.

---

## Table of contents

1. [Conventions](#1-conventions)
2. [Enumerations](#2-enumerations)
3. [Shared data models](#3-shared-data-models)
4. [Authentication](#4-authentication) — `/auth/*`
5. [Customer self-service](#5-customer-self-service) — register, profile, dashboard, pricing
6. [Orders](#6-orders) — statuses, cut-off, quote, create, list, detail
7. [Customer management (merchant)](#7-customer-management-merchant)
8. [KYC review (merchant)](#8-kyc-review-merchant)
9. [Pricing management (merchant)](#9-pricing-management-merchant)
10. [Delivery & dispatch (merchant)](#10-delivery--dispatch-merchant)
11. [Warehouse inventory (merchant)](#11-warehouse-inventory-merchant)
12. [Payments & invoices](#12-payments--invoices)
13. [Expenses (merchant)](#13-expenses-merchant)
14. [Reports (merchant)](#14-reports-merchant)
15. [Notifications](#15-notifications)
16. [Merchant dashboard](#16-merchant-dashboard)
17. [Document upload (new, Phase 2)](#17-document-upload-new-phase-2)
18. [Business rules the backend must enforce](#18-business-rules-the-backend-must-enforce)
19. [Endpoint index](#19-endpoint-index)

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | `env.apiBaseUrl` in `<app>/src/config/env.ts`, e.g. `https://api.mbga.in/api/v1`. All paths below are relative to it. |
| Transport | HTTPS, JSON (`Content-Type: application/json; charset=utf-8`). Multipart only for document upload (§17). |
| Auth header | `Authorization: Bearer <token>` on every endpoint marked **Auth: Yes**. Token comes from `POST /auth/otp/verify`. |
| App identity | The two installable apps send `appTarget: "customer" \| "merchant"` on the OTP endpoints. The backend must reject a mismatch (staff number in Customer app and vice-versa) with `code: "WRONG_APP"`. |
| Roles | `CUSTOMER`, `MANAGER`, `SALESPERSON`, `GODOWN_INCHARGE`, `ACCOUNTANT`. Drivers/helpers use a separate app and never call these APIs. |
| Permissions | Returned with the session (`user.permissions[]`). The app uses them **only for UX**; the backend must authorize every call itself (→ `403`). Default role→permission matrix is in §2. |
| Actor fields | `createdBy`, `collectedBy`, `recordedBy`, `reviewedBy`, `enteredBy`, `updatedBy` are **display names** the backend derives from the token (the mock passes them from the client — real API must not trust a client-supplied actor). |
| IDs | Opaque strings. Demo formats: `CUST-001`, `MBGA-R-0001` (customer code), `ORD-2606-0148`, `DS-0148`, `INV-0144` / `MBGA/INV/0144` (invoice number), `PAY-0211`, `EXP-0312`, `SM-0118`, `KYC-003`, `NTF-…`, `PRC-2026-06`, `SITE-002A`. |
| Dates | ISO-8601 UTC strings (`"2026-06-15T09:12:00.000Z"`). `reportPeriod` / `month` are `YYYY-MM`. `cutoffTime` is `HH:mm` local (IST). |
| Money | Integer **whole rupees** (`number`). No paise. Field type `Money` below = integer INR. |
| GST | **All prices are GST-inclusive.** `unitPrice`, `lineTotal`, `totalAmount` already include GST. `subtotal` (taxable value) `= round(totalAmount / (1 + gstPercent/100))`, `gstAmount = totalAmount − subtotal`. Never add GST on top. |
| Lists | Return plain JSON arrays (the app does not paginate in Phase 1). If pagination is required, wrap as `{ "items": [...], "total": n }` — the app has a `Paginated<T>` type ready; services will unwrap. |
| Sorting | Lists are returned newest-first unless stated. |
| Empty optionals | Omit the key or send `null`; the app treats both as absent. |
| Idempotency | `POST /orders`, `POST /payments`, `POST /inventory/movements` should accept an optional `Idempotency-Key` header (retries on flaky mobile networks). |
| Timeouts | App-side timeout is 15 s (`env.apiTimeoutMs` in `<app>/src/config/env.ts`). |

### 1.1 Error envelope

Every non-2xx response body:

```json
{
  "message": "Human-readable message shown to the user",
  "code": "OPTIONAL_MACHINE_CODE",
  "fieldErrors": { "fieldName": "Inline message shown under that input" }
}
```

| HTTP status | App error kind | Typical use |
|---|---|---|
| 400 / 422 | `VALIDATION` | Bad input. Use `fieldErrors` so the app can highlight and auto-focus the field. |
| 401 | `AUTHENTICATION` | Missing/expired token → app signs the user out. |
| 403 | `AUTHORIZATION` | Role/permission denied, customer not approved, `WRONG_APP`, `USER_INACTIVE`. |
| 404 | `NOT_FOUND` | Unknown id. |
| 409 | `CONFLICT` | State conflict (already reviewed, already delivered, duplicate mobile, insufficient stock). |
| 5xx | `SERVER` | Generic failure → toast "Something went wrong on our side". |

Machine codes the frontend reacts to specially: `WRONG_APP`, `USER_INACTIVE`, `OTP_INVALID`, `OTP_EXPIRED`.

`fieldErrors` keys the frontend binds to inputs are listed per endpoint (e.g. `mobile`, `amount`, `reference`, `otp`,
`emptiesCollected`, `quantity`, `fromBucket`, `bucket`, `newCount`, `note`, `items`, `deliverySiteId`,
`<CYLINDER_TYPE_CODE>`, `rejectionReason`).

---

## 2. Enumerations

| Enum | Values | Notes |
|---|---|---|
| `AppTarget` | `customer` · `merchant` | Which installed app is calling. |
| `UserRole` | `CUSTOMER` · `MANAGER` · `SALESPERSON` · `GODOWN_INCHARGE` · `ACCOUNTANT` | |
| `UserStatus` | `ACTIVE` · `INACTIVE` | `INACTIVE` → login blocked (`USER_INACTIVE`). |
| `CustomerAccountStatus` | `NEW` · `PENDING` · `APPROVED` · `REJECTED` · `SUSPENDED` | `NEW` = signed in, not registered. Only `APPROVED` may order. |
| `CustomerType` | `RETAIL` · `INDUSTRIAL` | Industrial may order the 422 KG Hippo and has delivery sites + GST invoices. |
| `KycStatus` | `NOT_SUBMITTED` · `PENDING` · `VERIFIED` · `REJECTED` | |
| `KycDocumentType` | `AADHAAR` · `PAN` · `FSSAI` · `GST` | Retail requires AADHAAR + PAN; Industrial requires FSSAI + GST. |
| `KycDocumentStatus` | `UPLOADED` · `VERIFIED` · `REJECTED` | |
| `KycApplicationStatus` | `PENDING` · `APPROVED` · `REJECTED` | |
| `PricingTier` | `STANDARD` · `PREFERRED` · `KEY_ACCOUNT` | Set by MBGA per customer. |
| `PricingMonthStatus` | `ACTIVE` · `DRAFT` · `ARCHIVED` | Exactly one `ACTIVE` month at a time. |
| `CylinderTypeCode` | `LPG_5KG` · `LPG_19KG` · `LPG_47_5KG_L` · `LPG_47_5KG_V` · `LPG_422KG_HIPPO` | Labels: 5 KG, 19 KG, 47.5 KG L (liquid), 47.5 KG V (vapour), 422 KG Hippo (**industrial only**). |
| `OrderStatusCode` | `PLACED` · `CONFIRMED` · `PREPARING` · `OUT_FOR_DELIVERY` · `DELIVERED` · `CANCELLED` | Free-form string in the app; the catalogue endpoint (§6.1) is authoritative. |
| `OrderMode` | `NEW` · `REPEAT` | |
| `OrderSource` | `CUSTOMER_APP` · `MERCHANT_APP` | |
| `DeliveryStatus` | `SCHEDULED` · `DISPATCHED` · `DELIVERED` · `FAILED` | |
| `ConfirmationMethod` | `OTP` · `SIGNATURE` · `PHOTO` · `NONE` | Phase 1 UI supports `OTP` and `NONE`. |
| `StockBucket` | `filled` · `empty` · `damaged` | |
| `StockMovementType` | `RECEIVED_FILLED` · `SENT_TO_PLANT` · `MARKED_DAMAGED` · `CORRECTION` · `DISPATCHED` · `EMPTIES_COLLECTED` | First four are manual (app posts them); last two are written by the delivery endpoints. |
| `PaymentMode` | `CASH` · `UPI` · `NEFT` | |
| `ReconciliationStatus` | `PENDING` · `RECONCILED` · `INVALID` | Cash → `RECONCILED` immediately; UPI/NEFT → `PENDING` until bank match. |
| `InvoiceStatus` | `UNPAID` · `PARTIAL` · `PAID` | |
| `ExpenseCategory` | `FUEL` · `VEHICLE_MAINTENANCE` · `SALARY` · `RENT` · `UTILITIES` · `MISC` | |
| `ReportType` | `DAILY_DELIVERY` · `PAYMENT_COLLECTION` · `PENDING_PICKUP` · `EXPENSE` | |
| `NotificationSeverity` | `INFO` · `WARNING` · `CRITICAL` | |
| `NotificationCategory` | `ORDER` · `DELIVERY` · `PAYMENT` · `ACCOUNT` · `STOCK` · `KYC` · `PRICING` · `SYSTEM` | |
| `ReferenceType` (notification) | `ORDER` · `PAYMENT` · `CUSTOMER` · `DELIVERY` · `KYC` | Deep-link target. |
| `StatusTone` | `success` · `warning` · `error` · `info` · `pending` · `neutral` | Colour hint for status chips. |

### 2.1 Permissions and default role matrix

| Permission | MANAGER | SALESPERSON | GODOWN_INCHARGE | ACCOUNTANT |
|---|:-:|:-:|:-:|:-:|
| `dashboard.view` | ✓ | ✓ | ✓ | ✓ |
| `customers.view` | ✓ | ✓ | | ✓ |
| `customers.create` | ✓ | ✓ | | |
| `customers.kyc.review` | ✓ | ✓ | | |
| `orders.view` | ✓ | ✓ | ✓ | ✓ |
| `orders.create` | ✓ | ✓ | | |
| `pricing.view` | ✓ | ✓ | | ✓ |
| `pricing.manage` | ✓ | | | ✓ |
| `delivery.view` | ✓ | | ✓ | |
| `delivery.confirm` (dispatch + confirm) | ✓ | | ✓ | |
| `inventory.view` | ✓ | | ✓ | |
| `inventory.adjust` | ✓ | | ✓ | |
| `payments.view` | ✓ | ✓ | | ✓ |
| `payments.record` | ✓ | | | ✓ |
| `expenses.view` | ✓ | | | ✓ |
| `expenses.add` | ✓ | | | ✓ |
| `reports.view` | ✓ | | | ✓ |
| `notifications.view` | ✓ | ✓ | ✓ | ✓ |

Customers (`role: CUSTOMER`) have `permissions: []`; their access is implied by ownership (they only see their own data).

---

## 3. Shared data models

Field tables use: **type** · **req** (✓ = always present) · notes.

### 3.1 `Address`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| line1 | string | ✓ | Shop / plot, street |
| line2 | string | | Landmark, area |
| city | string | ✓ | |
| state | string | ✓ | Default "Madhya Pradesh" in the form |
| pincode | string | ✓ | 6 digits |

### 3.2 `AuthUser`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | |
| mobile | string | ✓ | 10 digits, no country code |
| name | string | ✓ | Empty string for a `NEW` customer |
| role | `UserRole` | ✓ | |
| permissions | `Permission[]` | ✓ | `[]` for customers |
| status | `ACTIVE` \| `INACTIVE` | ✓ | |
| appTarget | `AppTarget` | ✓ | `customer` for customers, `merchant` for staff |
| customerId | string | | Customer only; absent while `customerStatus = NEW` |
| customerStatus | `CustomerAccountStatus` | | Customer only — drives routing (home / register / status screen) |
| branchName | string | | Staff only, e.g. "Indore Main Godown" |

### 3.3 `AuthSession`
| Field | Type | Req |
|---|---|:-:|
| token | string | ✓ |
| expiresAt | ISO date | ✓ |
| user | `AuthUser` | ✓ |

### 3.4 `KycDocument` (as returned — identifiers **masked** server-side)
| Field | Type | Req | Notes |
|---|---|:-:|---|
| type | `KycDocumentType` | ✓ | |
| numberMasked | string | ✓ | e.g. `XXXX XXXX 4821`, `XXXXX1234F`. Full number is never returned. |
| fileName | string | ✓ | Display name (or file id) |
| uploadedAt | ISO date | ✓ | |
| status | `UPLOADED` \| `VERIFIED` \| `REJECTED` | ✓ | |

### 3.5 `DeliverySite`
| Field | Type | Req |
|---|---|:-:|
| id | string | ✓ |
| name | string | ✓ |
| address | `Address` | ✓ |
| contactName | string | |
| contactMobile | string | |
| isPrimary | boolean | ✓ |

### 3.6 `Customer`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | |
| code | string | ✓ | `MBGA-R-0001` / `MBGA-I-0002` |
| customerType | `CustomerType` | ✓ | |
| businessName | string | ✓ | |
| ownerName | string | ✓ | |
| mobile | string | ✓ | Login number |
| email | string | | |
| accountStatus | `CustomerAccountStatus` | ✓ | |
| kycStatus | `KycStatus` | ✓ | |
| pricingTier | `PricingTier` | ✓ | |
| deliveryAddress | `Address` | ✓ | Registered / primary address |
| sites | `DeliverySite[]` | ✓ | `[]` for retail; industrial has ≥1 with the primary first |
| documents | `KycDocument[]` | ✓ | |
| gstin | string | | Industrial only |
| registeredAt | ISO date | ✓ | |
| approvedAt | ISO date | | |
| rejectionReason | string | | When `accountStatus = REJECTED` |
| runningBalance | Money | ✓ | Σ open invoice balances |
| lastOrderAt | ISO date | | |

### 3.7 `KycApplication`
| Field | Type | Req |
|---|---|:-:|
| id | string | ✓ |
| customerId | string | ✓ |
| customerType | `CustomerType` | ✓ |
| businessName · ownerName · mobile | string | ✓ |
| email | string | |
| documents | `KycDocument[]` | ✓ |
| deliveryAddress | `Address` | ✓ |
| sites | `DeliverySite[]` | ✓ |
| status | `PENDING` \| `APPROVED` \| `REJECTED` | ✓ |
| submittedAt | ISO date | ✓ |
| reviewedAt · reviewedBy · rejectionReason | ISO date · string · string | |

### 3.8 `CutoffInfo`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| cutoffTime | string `HH:mm` | ✓ | `"16:00"` |
| withinCutoff | boolean | ✓ | Order now → next-day delivery? |
| scheduledDeliveryDate | ISO date | ✓ | |
| message | string | ✓ | Shown verbatim to the user |

### 3.9 `OrderItem`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| cylinderType | `CylinderTypeCode` | ✓ | |
| cylinderLabel | string | ✓ | "19 KG" |
| quantity | integer | ✓ | |
| unitPrice | Money | ✓ | **GST-inclusive** per cylinder |
| lineTotal | Money | ✓ | `unitPrice × quantity` |

### 3.10 `Order`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | |
| orderNumber | string | ✓ | `ORD-2606-0148` |
| customerId · customerName | string | ✓ | |
| customerType | `CustomerType` | ✓ | |
| items | `OrderItem[]` | ✓ | An order can mix cylinder types |
| totalCylinders | integer | ✓ | Σ quantity |
| itemsSummary | string | ✓ | `"4 × 19 KG · 6 × 5 KG"` (display only) |
| orderMode | `OrderMode` | ✓ | |
| source | `OrderSource` | ✓ | |
| deliverySiteId | string | | Industrial |
| deliverySiteName | string | ✓ | `"Registered delivery address"` when no site |
| deliveryAddress | `Address` | ✓ | |
| subtotal | Money | ✓ | Taxable value (total − GST) |
| gstPercent | number | ✓ | 18 |
| gstAmount | Money | ✓ | Included in total |
| totalAmount | Money | ✓ | Σ lineTotal |
| status | `OrderStatusCode` | ✓ | |
| statusHistory | `{ status, at, by?, note? }[]` | ✓ | Oldest first |
| placedAt | ISO date | ✓ | |
| cutoff | `CutoffInfo` | ✓ | As evaluated at placement |
| deliverySlot | string | | `"09:00 AM – 01:00 PM"` |
| createdBy | string | | Staff name when placed from Merchant app |
| deliverySlipId | string | | |
| invoiceId | string | | |

### 3.11 `OrderStatusMeta`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| code | string | ✓ | |
| label | string | ✓ | |
| sequence | integer | ✓ | Timeline order; terminal failure states use 99 |
| tone | `StatusTone` | ✓ | |
| description | string | ✓ | |
| isTerminal | boolean | ✓ | |

### 3.12 `DeliverySlip`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | `DS-0148` |
| orderId · orderNumber | string | ✓ | |
| customerId · customerName | string | ✓ | |
| deliveryAddress | `Address` | ✓ | |
| deliverySiteName | string | ✓ | |
| items | `{ cylinderType, cylinderLabel, quantity }[]` | ✓ | |
| itemsSummary | string | ✓ | |
| cylindersAllocated | integer | ✓ | Σ items.quantity |
| vehicleNumber | string | ✓ | `"MP09 GH 4521"` |
| driverName | string | ✓ | |
| helperName | string | | |
| scheduledDate | ISO date | ✓ | |
| dispatchedAt · deliveredAt | ISO date | | |
| emptiesCollected | integer | ✓ | 0 until confirmed |
| pendingPickup | integer | ✓ | `cylindersAllocated − emptiesCollected` after delivery |
| confirmationMethod | `ConfirmationMethod` | ✓ | |
| status | `DeliveryStatus` | ✓ | |

### 3.13 `StockItem`, `StockAlert`, `StockMovement`
`StockItem`: `cylinderType`, `cylinderLabel`, `filled`, `empty`, `damaged` (integers), `reorderThreshold`, `updatedAt`.
`StockAlert`: `id`, `cylinderType`, `severity` (`NotificationSeverity`), `message`.
`StockMovement`:
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | |
| type | `StockMovementType` | ✓ | |
| cylinderType · cylinderLabel | string | ✓ | |
| quantity | integer | ✓ | Always positive |
| deltas | `{ filled?: int, empty?: int, damaged?: int }` | ✓ | Signed bucket changes, e.g. `{ "empty": -2, "damaged": 2 }` |
| note | string | | |
| referenceType | `ORDER` \| `DELIVERY` \| `CHALLAN` | | |
| referenceId | string | | Slip id / challan no. |
| recordedBy | string | ✓ | Staff display name |
| recordedAt | ISO date | ✓ | |

### 3.14 `Invoice`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | `INV-0144` |
| invoiceNumber | string | ✓ | `MBGA/INV/0144` |
| orderId · orderNumber | string | ✓ | |
| customerId · customerName | string | ✓ | |
| amount | Money | ✓ | Taxable value |
| gstPercent | number | ✓ | |
| gstAmount | Money | ✓ | |
| totalAmount | Money | ✓ | |
| paidAmount · balance | Money | ✓ | |
| status | `InvoiceStatus` | ✓ | |
| issuedAt · dueAt | ISO date | ✓ | |
| isGstInvoice | boolean | ✓ | true for industrial |
| gstin | string | | |

### 3.15 `Payment`
| Field | Type | Req | Notes |
|---|---|:-:|---|
| id | string | ✓ | `PAY-0211` |
| invoiceId · invoiceNumber | string | ✓ | |
| customerId · customerName | string | ✓ | |
| invoiceAmount | Money | ✓ | |
| amountCollected | Money | ✓ | |
| mode | `PaymentMode` | ✓ | |
| paidAt | ISO date | ✓ | |
| reference | string | | UTR / UPI ref / receipt no. |
| reconciliationStatus | `ReconciliationStatus` | ✓ | |
| invalidReason | string | | When `INVALID` |
| collectedBy | string | | |
| customerRunningBalance | Money | ✓ | Balance after this payment |

### 3.16 `Expense`
`id`, `category` (`ExpenseCategory`), `amount` (Money), `date` (ISO), `enteredBy`, `reportPeriod` (`YYYY-MM`), `note?`.

### 3.17 `PricingMonth`, `PriceEntry`, `CustomerPrice`
`PriceEntry`: `cylinderType`, `tier`, `bpclBaseRate` (Money), `tierMarkup` (Money), `customerPrice` (= base + markup, GST-inclusive).
`PricingMonth`: `id`, `month` (`YYYY-MM`), `label` ("June 2026"), `effectiveFrom`, `effectiveTo`, `status`, `gstPercent`, `entries: PriceEntry[]` (5 cylinders × 3 tiers = 15), `updatedBy`, `updatedAt`.
`CustomerPrice`: `cylinderType`, `cylinderLabel`, `price` (Money, inclusive), `tier`, `gstPercent`, `effectiveFrom`, `effectiveTo`.

### 3.18 `AppNotification`
`id`, `title`, `message`, `severity`, `category`, `createdAt`, `read` (boolean), `referenceType?`, `referenceId?`.

### 3.19 `Report`
`type`, `title`, `period: { from, to }`, `summary: { label, value }[]`, `columns: { key, label, align?: "left"|"right" }[]`, `rows: Record<string, string|number>[]` (each row **must** include `id`), `generatedAt`.

### 3.20 Dashboards
`MerchantDashboard`: `kpis` (see §16), `alerts: AppNotification[]`, `recentOrders: Order[]`, `recentRegistrations: KycApplication[]`, `asOf`.
`CustomerDashboard`: `customer: Customer`, `currentOrder?: Order`, `recentOrder?: Order`, `pricing: CustomerPrice[]`, `paymentSummary: CustomerPaymentSummary`, `unreadNotifications: integer`.
`CustomerPaymentSummary`: `totalInvoiced`, `totalPaid`, `runningBalance`, `overdueAmount` (Money), `lastPaymentAt?`.

---

## 4. Authentication

OTP is the **only** login method. 4-digit OTP, 120 s validity, resend allowed after 30 s, max 3 wrong attempts.

### 4.1 Send OTP
| | |
|---|---|
| **Endpoint** | `POST /auth/otp/send` |
| **Auth** | No |
| **Used by** | Login screens (both apps) · `authService.sendOtp` |

**Request body**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| mobile | string | ✓ | Exactly 10 digits |
| appTarget | `AppTarget` | ✓ | Installed app |

**Backend rules**
- Look up the mobile. Staff number + `appTarget=customer` → `403 WRONG_APP` ("This number is registered as MBGA staff. Please use the MBGA Merchant app."). Non-staff number + `appTarget=merchant` → `403 WRONG_APP` ("This number is not registered as MBGA staff…").
- Unknown number in the **Customer** app is allowed (new customer → registration after verify).
- `status = INACTIVE` → `403 USER_INACTIVE`.
- Rate-limit per mobile.

**Response `200`**
| Field | Type | Notes |
|---|---|---|
| requestId | string | Echoed back on verify/resend |
| expiresInSeconds | integer | 120 |
| resendAfterSeconds | integer | 30 |
| devOtp | string | **Mock only — must NOT exist in production** |

```json
// request
{ "mobile": "9000000001", "appTarget": "customer" }
// response
{ "requestId": "otp-m1x9k2", "expiresInSeconds": 120, "resendAfterSeconds": 30 }
```

**Errors:** `400` invalid mobile · `403 WRONG_APP` · `403 USER_INACTIVE` · `429` too many requests · `503` SMS provider down.

### 4.2 Verify OTP
| | |
|---|---|
| **Endpoint** | `POST /auth/otp/verify` |
| **Auth** | No |
| **Used by** | Login screens · `authService.verifyOtp` |

**Request body**
| Field | Type | Req |
|---|---|:-:|
| requestId | string | ✓ |
| mobile | string | ✓ |
| otp | string | ✓ (4 digits) |
| appTarget | `AppTarget` | ✓ |

**Response `200`** — `AuthSession` (§3.3). For an unknown number in the Customer app, create a user with
`role: CUSTOMER`, `customerStatus: "NEW"`, no `customerId` — the app routes to registration.

```json
{
  "token": "eyJhbGciOi…",
  "expiresAt": "2026-06-22T09:12:00.000Z",
  "user": {
    "id": "USR-C001", "mobile": "9000000001", "name": "Rajendra Sharma",
    "role": "CUSTOMER", "permissions": [], "status": "ACTIVE", "appTarget": "customer",
    "customerId": "CUST-001", "customerStatus": "APPROVED"
  }
}
```
Staff example `user`:
```json
{ "id": "USR-M001", "mobile": "9100000001", "name": "Rajesh Verma", "role": "MANAGER",
  "permissions": ["dashboard.view","customers.view","customers.create","customers.kyc.review","orders.view","orders.create","pricing.view","pricing.manage","delivery.view","delivery.confirm","inventory.view","inventory.adjust","payments.view","payments.record","expenses.view","expenses.add","reports.view","notifications.view"],
  "status": "ACTIVE", "appTarget": "merchant", "branchName": "Indore Main Godown" }
```

**Errors**
| HTTP | code | message | App behaviour |
|---|---|---|---|
| 400 | `OTP_INVALID` | "Incorrect OTP. 2 attempts left." | Inline error, clears boxes |
| 400 | `OTP_EXPIRED` | "This OTP has expired…" / "Too many incorrect attempts…" | Expired state + Resend button |
| 404 | — | "OTP request not found." | Restart |
| 403 | `WRONG_APP` / `USER_INACTIVE` | as in 4.1 | Inline error |

### 4.3 Resend OTP
| | |
|---|---|
| **Endpoint** | `POST /auth/otp/resend` |
| **Auth** | No |
| **Used by** | `authService.resendOtp` |

**Request** `{ "requestId": "otp-m1x9k2", "appTarget": "customer" }` → **Response** same as 4.1 (new `requestId`).
**Errors:** `404` unknown request · `429` before `resendAfterSeconds`.

### 4.4 Current session (restore)
| | |
|---|---|
| **Endpoint** | `GET /auth/me` |
| **Auth** | Yes |
| **Used by** | App launch (splash) · `authService.restoreSession` |

**Response `200`** — `AuthUser` (fresh `customerStatus` / `permissions`, e.g. KYC approved while the app was closed).
**Errors:** `401` → app signs out.

### 4.5 Logout
| | |
|---|---|
| **Endpoint** | `POST /auth/logout` |
| **Auth** | Yes |
| **Used by** | Profile / More → Sign out · `authService.logout` |

**Request** empty. **Response** `204`. Must invalidate the token.

---

## 5. Customer self-service

### 5.1 Register (self sign-up)
| | |
|---|---|
| **Endpoint** | `POST /customers/register` |
| **Auth** | Yes — session with `customerStatus: NEW` |
| **Used by** | Customer → 3-step registration · `customerService.register` |

**Request body — `CustomerRegistrationRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| customerType | `CustomerType` | ✓ | |
| businessName | string | ✓ | non-empty |
| ownerName | string | ✓ | non-empty |
| mobile | string | ✓ | Must equal the token's mobile |
| email | string | | valid email |
| deliveryAddress | `Address` | ✓ | line1, city, state, 6-digit pincode |
| documents | `{ type, number, fileName }[]` | ✓ | RETAIL: `AADHAAR` (12 digits) + `PAN` (`ABCDE1234F`). INDUSTRIAL: `FSSAI` (14 digits) + `GST` (15-char GSTIN e.g. `23AAACA1234F1Z5`). `fileName` = uploaded file id (§17) |
| sites | `{ name, address, contactName?, contactMobile? }[]` | | INDUSTRIAL only; the app sends the primary site first (`"Primary site"` = deliveryAddress) plus extra sites |

**Response `201`** — `Customer` with `accountStatus: "PENDING"`, `kycStatus: "PENDING"`, documents `UPLOADED` with masked numbers.
Side effects: create `KycApplication` (PENDING), set user `customerStatus = PENDING`, notify customer ("Application received") and merchant bucket ("New KYC application").

```json
// request
{
  "customerType": "RETAIL",
  "businessName": "Test Bakery", "ownerName": "Ravi Kumar", "mobile": "9000000099",
  "email": "ravi@testbakery.in",
  "deliveryAddress": { "line1": "12 MG Road", "line2": "", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001" },
  "documents": [
    { "type": "AADHAAR", "number": "123412341234", "fileName": "aadhaar_m1x9k2.pdf" },
    { "type": "PAN", "number": "ABCDE1234F", "fileName": "pan_m1x9k3.pdf" }
  ]
}
// response 201
{
  "id": "CUST-011", "code": "MBGA-R-0011", "customerType": "RETAIL",
  "businessName": "Test Bakery", "ownerName": "Ravi Kumar", "mobile": "9000000099", "email": "ravi@testbakery.in",
  "accountStatus": "PENDING", "kycStatus": "PENDING", "pricingTier": "STANDARD",
  "deliveryAddress": { "line1": "12 MG Road", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001" },
  "sites": [],
  "documents": [
    { "type": "AADHAAR", "numberMasked": "XXXXXXXX1234", "fileName": "aadhaar_m1x9k2.pdf", "uploadedAt": "2026-06-15T09:12:00.000Z", "status": "UPLOADED" },
    { "type": "PAN", "numberMasked": "XXXXXX234F", "fileName": "pan_m1x9k3.pdf", "uploadedAt": "2026-06-15T09:12:00.000Z", "status": "UPLOADED" }
  ],
  "registeredAt": "2026-06-15T09:12:00.000Z", "runningBalance": 0
}
```
**Errors:** `422` with `fieldErrors` (`businessName`, `ownerName`, `email`, `address.line1`, `address.city`, `address.pincode`, `address.state`, `doc.AADHAAR.number`, `doc.PAN.file`, …) · `409` "A customer with this mobile number already exists." · `401`.

### 5.2 My profile
| | |
|---|---|
| **Endpoint** | `GET /customers/me` |
| **Auth** | Yes (customer) |
| **Used by** | Profile, Application Status · `customerService.getMyProfile` |

**Response `200`** — `Customer`. **Errors:** `404` if not registered.

### 5.3 Customer dashboard
| | |
|---|---|
| **Endpoint** | `GET /dashboard/customer` |
| **Auth** | Yes (customer, APPROVED) |
| **Used by** | Customer Home · `dashboardService.getCustomerDashboard` |

**Response `200`** — `CustomerDashboard`:
```json
{
  "customer": { "...": "Customer" },
  "currentOrder": { "id": "ORD-2606-0148", "status": "OUT_FOR_DELIVERY", "...": "Order" },
  "recentOrder": { "id": "ORD-2606-0141", "status": "DELIVERED", "...": "Order" },
  "pricing": [ { "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "price": 1800, "tier": "STANDARD", "gstPercent": 18, "effectiveFrom": "2026-06-01T00:00:00.000Z", "effectiveTo": "2026-06-30T23:59:59.000Z" } ],
  "paymentSummary": { "totalInvoiced": 14940, "totalPaid": 11400, "runningBalance": 3540, "overdueAmount": 0, "lastPaymentAt": "2026-06-11T14:25:00.000Z" },
  "unreadNotifications": 2
}
```
`currentOrder` = newest non-terminal order; `recentOrder` = newest terminal order.

### 5.4 Customer pricing
| | |
|---|---|
| **Endpoint** | `GET /pricing/customers/{customerId}` |
| **Auth** | Yes — customer (own id) or staff with `pricing.view` |
| **Used by** | My Pricing, Place Order picker, merchant Customer detail · `pricingService.getCustomerPricing` |

**Response `200`** — `CustomerPrice[]` from the **ACTIVE** pricing month for the customer's tier, filtered to cylinders the customer may order (Hippo only for industrial).
```json
[
  { "cylinderType": "LPG_5KG", "cylinderLabel": "5 KG", "price": 490, "tier": "STANDARD", "gstPercent": 18, "effectiveFrom": "2026-06-01T00:00:00.000Z", "effectiveTo": "2026-06-30T23:59:59.000Z" },
  { "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "price": 1800, "tier": "STANDARD", "gstPercent": 18, "effectiveFrom": "…", "effectiveTo": "…" },
  { "cylinderType": "LPG_47_5KG_L", "cylinderLabel": "47.5 KG L", "price": 4500, "tier": "STANDARD", "gstPercent": 18, "effectiveFrom": "…", "effectiveTo": "…" },
  { "cylinderType": "LPG_47_5KG_V", "cylinderLabel": "47.5 KG V", "price": 4535, "tier": "STANDARD", "gstPercent": 18, "effectiveFrom": "…", "effectiveTo": "…" }
]
```
**Errors:** `404` customer / no active pricing.

---

## 6. Orders

### 6.1 Order status catalogue
| | |
|---|---|
| **Endpoint** | `GET /orders/statuses` |
| **Auth** | Yes |
| **Used by** | Order tracking timeline, filters · `orderService.getOrderStatuses` |

**Response `200`** — `OrderStatusMeta[]` sorted by `sequence`. The UI renders the timeline from this — **no transitions are hard-coded in the app**.
```json
[
  { "code": "PLACED", "label": "Order Placed", "sequence": 1, "tone": "info", "description": "We have received your order.", "isTerminal": false },
  { "code": "CONFIRMED", "label": "Confirmed", "sequence": 2, "tone": "info", "description": "Order confirmed and scheduled for delivery.", "isTerminal": false },
  { "code": "PREPARING", "label": "Preparing / Dispatch", "sequence": 3, "tone": "pending", "description": "Cylinders are being allocated at the godown.", "isTerminal": false },
  { "code": "OUT_FOR_DELIVERY", "label": "Out for Delivery", "sequence": 4, "tone": "warning", "description": "Your cylinders are on the way.", "isTerminal": false },
  { "code": "DELIVERED", "label": "Delivered", "sequence": 5, "tone": "success", "description": "Delivered and confirmed.", "isTerminal": true },
  { "code": "CANCELLED", "label": "Cancelled", "sequence": 99, "tone": "error", "description": "This order was cancelled.", "isTerminal": true }
]
```

### 6.2 Cut-off info
| | |
|---|---|
| **Endpoint** | `GET /orders/cutoff` |
| **Auth** | Yes |
| **Used by** | Place Order / Create Order banner · `orderService.getCutoffInfo` |

**Response `200`** — `CutoffInfo`. Rule: orders before **16:00 IST** → next-day delivery; after → day after tomorrow.
```json
{ "cutoffTime": "16:00", "withinCutoff": true, "scheduledDeliveryDate": "2026-06-16T09:00:00.000Z", "message": "Order before 4:00 PM for next-day delivery." }
```

### 6.3 Order quote
| | |
|---|---|
| **Endpoint** | `POST /orders/quote` |
| **Auth** | Yes — customer (own id) or staff `orders.create` |
| **Used by** | Live price summary while picking cylinders · `orderService.getQuote` |

**Request body — `OrderQuoteRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| customerId | string | ✓ | |
| items | `{ cylinderType, quantity }[]` | ✓ | ≥1 line; duplicates merged; quantity limits per §18.3; Hippo only for INDUSTRIAL |

**Response `200`** — `OrderQuote`: `items: OrderItem[]`, `totalCylinders`, `subtotal`, `gstPercent`, `gstAmount`, `totalAmount`, `cutoff`.
```json
// request
{ "customerId": "CUST-001", "items": [ { "cylinderType": "LPG_19KG", "quantity": 2 }, { "cylinderType": "LPG_5KG", "quantity": 1 } ] }
// response — prices are GST-inclusive; GST is broken OUT of the total
{
  "items": [
    { "cylinderType": "LPG_5KG",  "cylinderLabel": "5 KG",  "quantity": 1, "unitPrice": 490,  "lineTotal": 490 },
    { "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 2, "unitPrice": 1800, "lineTotal": 3600 }
  ],
  "totalCylinders": 3,
  "totalAmount": 4090,
  "gstPercent": 18,
  "subtotal": 3466,
  "gstAmount": 624,
  "cutoff": { "cutoffTime": "16:00", "withinCutoff": true, "scheduledDeliveryDate": "2026-06-16T09:00:00.000Z", "message": "Order before 4:00 PM for next-day delivery." }
}
```
**Errors:** `422 fieldErrors.items` "Add at least one cylinder" · `422 fieldErrors.<CYLINDER_TYPE>` "Enter 1–50" · `422` "422 KG Hippo is only available to industrial customers." · `404` customer.

### 6.4 Create order
| | |
|---|---|
| **Endpoint** | `POST /orders` |
| **Auth** | Yes — customer (own id, APPROVED) or staff `orders.create` |
| **Used by** | Customer Place Order → **Confirm Order**; Merchant Create Order → **Create Order** · `orderService.createOrder` |

**Request body — `CreateOrderRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| customerId | string | ✓ | |
| items | `{ cylinderType, quantity }[]` | ✓ | as in 6.3 |
| orderMode | `NEW` \| `REPEAT` | ✓ | |
| deliverySiteId | string | cond. | **Required for INDUSTRIAL** customers; must be one of `customer.sites[].id` |
| source | `CUSTOMER_APP` \| `MERCHANT_APP` | ✓ | Backend may also infer from role |

**Response `201`** — `Order` with `status: "PLACED"`, priced from the ACTIVE month, `statusHistory[0] = { status: PLACED, at, by? }`,
`deliverySlot` `"09:00 AM – 01:00 PM"` (within cut-off) or `"02:00 PM – 06:00 PM"`. Side effects: customer notification "Order placed", merchant notification "New order received", `customer.lastOrderAt`.
```json
// request
{ "customerId": "CUST-002", "items": [ { "cylinderType": "LPG_47_5KG_L", "quantity": 6 }, { "cylinderType": "LPG_47_5KG_V", "quantity": 2 } ],
  "orderMode": "NEW", "deliverySiteId": "SITE-002A", "source": "MERCHANT_APP" }
// response 201
{
  "id": "ORD-2606-0151", "orderNumber": "ORD-2606-0151",
  "customerId": "CUST-002", "customerName": "Apex Foods Pvt Ltd", "customerType": "INDUSTRIAL",
  "items": [
    { "cylinderType": "LPG_47_5KG_L", "cylinderLabel": "47.5 KG L", "quantity": 6, "unitPrice": 4375, "lineTotal": 26250 },
    { "cylinderType": "LPG_47_5KG_V", "cylinderLabel": "47.5 KG V", "quantity": 2, "unitPrice": 4410, "lineTotal": 8820 }
  ],
  "totalCylinders": 8, "itemsSummary": "6 × 47.5 L · 2 × 47.5 V",
  "orderMode": "NEW", "source": "MERCHANT_APP",
  "deliverySiteId": "SITE-002A", "deliverySiteName": "Plant A — Sanwer Road",
  "deliveryAddress": { "line1": "Plot 22, Sector C, Sanwer Road Industrial Area", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452015" },
  "subtotal": 29720, "gstPercent": 18, "gstAmount": 5350, "totalAmount": 35070,
  "status": "PLACED",
  "statusHistory": [ { "status": "PLACED", "at": "2026-06-15T09:12:00.000Z", "by": "Priya Nair" } ],
  "placedAt": "2026-06-15T09:12:00.000Z",
  "cutoff": { "cutoffTime": "16:00", "withinCutoff": true, "scheduledDeliveryDate": "2026-06-16T09:00:00.000Z", "message": "Order before 4:00 PM for next-day delivery." },
  "deliverySlot": "09:00 AM – 01:00 PM", "createdBy": "Priya Nair"
}
```
**Errors:** `403` "Only approved customers can place orders." · `422 fieldErrors.deliverySiteId` "Delivery site is required" · quote errors from 6.3 · `404`.

### 6.5 List orders
| | |
|---|---|
| **Endpoint** | `GET /orders` |
| **Auth** | Yes — customers see only their own; staff `orders.view` |
| **Used by** | Orders tab (both apps), Customer detail history · `orderService.listOrders` |

**Query params**
| Param | Type | Notes |
|---|---|---|
| customerId | string | Staff filter (ignored/forced for customers) |
| status | `OrderStatusCode` \| `ALL` \| `ACTIVE` | `ACTIVE` = every non-terminal status |
| search | string | Matches orderNumber, customerName, itemsSummary (case-insensitive) |

**Response `200`** — `Order[]` newest first.

### 6.6 Order detail
| | |
|---|---|
| **Endpoint** | `GET /orders/{id}` |
| **Auth** | Yes (owner or staff) |
| **Used by** | Order detail / tracking (both apps) · `orderService.getOrder` |

**Response `200`** — `Order`. **Errors:** `404`.

---

## 7. Customer management (merchant)

### 7.1 Staff adds a customer
| | |
|---|---|
| **Endpoint** | `POST /customers` |
| **Auth** | Yes — `customers.create` (Manager, Salesperson) |
| **Used by** | Dashboard → Add Customer / Customers → **+** · `customerService.createByStaff` |

**Request body** — same `CustomerRegistrationRequest` as §5.1, but `mobile` is the **customer's** number typed by staff.

**Backend rules**
- `mobile` belongs to a staff user → `422 fieldErrors.mobile = "This number belongs to MBGA staff"`.
- A customer with that mobile exists → `409` + `fieldErrors.mobile = "A customer with this mobile already exists"`.
- Create the customer **login** for that mobile if it doesn't exist, then the customer + KYC application (PENDING). The customer can immediately sign in to the Customer app and sees "Verification Pending".
- Notify merchant bucket: "New KYC application — {business} was added by {staff} and is awaiting review."

**Response `201`** — `Customer` (`accountStatus: PENDING`). Sample as in §5.1.

### 7.2 List customers
| | |
|---|---|
| **Endpoint** | `GET /customers` |
| **Auth** | Yes — `customers.view` |
| **Used by** | Customers tab, Create Order customer picker · `customerService.listCustomers` |

**Query params**
| Param | Type | Notes |
|---|---|---|
| search | string | businessName, ownerName, mobile, code |
| customerType | `RETAIL` \| `INDUSTRIAL` \| `ALL` | |
| accountStatus | `CustomerAccountStatus` \| `ALL` | The app uses `PENDING` for the "Pending" chip |

**Response `200`** — `Customer[]` sorted by `businessName` A→Z.
```json
[
  { "id": "CUST-002", "code": "MBGA-I-0002", "customerType": "INDUSTRIAL", "businessName": "Apex Foods Pvt Ltd", "ownerName": "Neha Kulkarni",
    "mobile": "9000000002", "email": "procurement@apexfoods.in", "accountStatus": "APPROVED", "kycStatus": "VERIFIED", "pricingTier": "KEY_ACCOUNT", "gstin": "23AAACA1234F1Z5",
    "deliveryAddress": { "line1": "Plot 22, Sector C, Sanwer Road Industrial Area", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452015" },
    "sites": [
      { "id": "SITE-002A", "name": "Plant A — Sanwer Road", "address": { "line1": "Plot 22, Sector C, Sanwer Road Industrial Area", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452015" }, "contactName": "Ramesh Patil", "contactMobile": "9822001122", "isPrimary": true },
      { "id": "SITE-002B", "name": "Plant B — Pithampur", "address": { "line1": "Unit 7, Sector 3, Pithampur Industrial Area", "city": "Pithampur", "state": "Madhya Pradesh", "pincode": "454775" }, "contactName": "Sanjay Dubey", "contactMobile": "9822003344", "isPrimary": false }
    ],
    "documents": [
      { "type": "FSSAI", "numberMasked": "XXXXXXXXXX7712", "fileName": "fssai_licence.pdf", "uploadedAt": "2025-11-27T09:00:00.000Z", "status": "VERIFIED" },
      { "type": "GST", "numberMasked": "23XXXXXXXXXX1Z5", "fileName": "gst_certificate.pdf", "uploadedAt": "2025-11-27T09:00:00.000Z", "status": "VERIFIED" }
    ],
    "registeredAt": "2025-11-27T09:00:00.000Z", "approvedAt": "2025-11-30T09:00:00.000Z", "runningBalance": 41300, "lastOrderAt": "2026-06-15T08:40:00.000Z" }
]
```

### 7.3 Customer detail
| | |
|---|---|
| **Endpoint** | `GET /customers/{id}` |
| **Auth** | Yes — `customers.view` |
| **Used by** | Customer detail, Create Order · `customerService.getCustomer` |

**Response `200`** — `Customer`. **Errors:** `404`.

### 7.4 Order eligibility
| | |
|---|---|
| **Endpoint** | `GET /customers/{id}/eligibility` |
| **Auth** | Yes — `orders.create` |
| **Used by** | Create Order (disables the form with reasons) · `customerService.checkEligibility` |

**Response `200`**
```json
{ "eligible": false, "reasons": [ "Account is pending — only approved customers can order.", "KYC is not verified." ] }
```
Eligible ⇔ `accountStatus = APPROVED` and `kycStatus = VERIFIED` (add credit-limit rules here later).

---

## 8. KYC review (merchant)

### 8.1 List applications
| | |
|---|---|
| **Endpoint** | `GET /kyc/applications` |
| **Auth** | Yes — `customers.kyc.review` |
| **Used by** | KYC Approvals list · `customerService.listKycApplications` |

**Query** `status = PENDING (default) | APPROVED | REJECTED | ALL`.
**Response `200`** — `KycApplication[]` newest `submittedAt` first.
```json
[
  { "id": "KYC-003", "customerId": "CUST-003", "customerType": "RETAIL", "businessName": "Royal Dhaba", "ownerName": "Gurpreet Singh", "mobile": "9000000003",
    "documents": [
      { "type": "AADHAAR", "numberMasked": "XXXX XXXX 9034", "fileName": "aadhaar.jpg", "uploadedAt": "2026-06-13T14:20:00.000Z", "status": "UPLOADED" },
      { "type": "PAN", "numberMasked": "XXXXX7788K", "fileName": "pan.jpg", "uploadedAt": "2026-06-13T14:20:00.000Z", "status": "UPLOADED" }
    ],
    "deliveryAddress": { "line1": "NH-3 Bypass, Opp. Petrol Pump, Rau", "city": "Indore", "state": "Madhya Pradesh", "pincode": "453331" },
    "sites": [], "status": "PENDING", "submittedAt": "2026-06-13T14:20:00.000Z" }
]
```

### 8.2 Application detail
| | |
|---|---|
| **Endpoint** | `GET /kyc/applications/{id}` |
| **Auth** | Yes — `customers.kyc.review` |
| **Used by** | Review Application · `customerService.getKycApplication` |

**Response `200`** — `KycApplication`. Document files are opened via §17.2.

### 8.3 Decide (approve / reject)
| | |
|---|---|
| **Endpoint** | `POST /kyc/applications/{id}/decision` |
| **Auth** | Yes — `customers.kyc.review` |
| **Used by** | Review Application → **Approve** / **Reject** · `customerService.decideKyc` |

**Request body — `KycDecisionRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| decision | `APPROVE` \| `REJECT` | ✓ | |
| rejectionReason | string | REJECT | ≥10 chars (app-side); required server-side |

(`applicationId` is in the path; the app also sends it in the body today — accept or ignore.)

**Backend rules:** only `PENDING` can be decided (`409` otherwise). APPROVE → customer `accountStatus=APPROVED`, `kycStatus=VERIFIED`, documents `VERIFIED`, `approvedAt`; user `customerStatus=APPROVED`; notify customer "Account approved". REJECT → `REJECTED` everywhere, store `rejectionReason`, notify customer (CRITICAL).

**Response `200`** — updated `KycApplication`:
```json
// request
{ "decision": "REJECT", "rejectionReason": "GST certificate does not match the business name" }
// response
{ "id": "KYC-004", "customerId": "CUST-004", "status": "REJECTED", "reviewedAt": "2026-06-15T10:05:00.000Z", "reviewedBy": "Rajesh Verma",
  "rejectionReason": "GST certificate does not match the business name", "...": "rest of KycApplication" }
```
**Errors:** `422 fieldErrors.rejectionReason` "Rejection reason is required" · `409` "This application has already been reviewed." · `404`.

---

## 9. Pricing management (merchant)

### 9.1 Pricing months
| | |
|---|---|
| **Endpoint** | `GET /pricing/months` |
| **Auth** | Yes — `pricing.view` |
| **Used by** | Pricing screen (month tabs, rate table) · `pricingService.getPricingMonths` |

**Response `200`** — `PricingMonth[]` newest month first.
```json
[
  { "id": "PRC-2026-06", "month": "2026-06", "label": "June 2026", "effectiveFrom": "2026-06-01T00:00:00.000Z", "effectiveTo": "2026-06-30T23:59:59.000Z",
    "status": "ACTIVE", "gstPercent": 18,
    "entries": [
      { "cylinderType": "LPG_5KG",  "tier": "STANDARD",    "bpclBaseRate": 445,   "tierMarkup": 45,   "customerPrice": 490 },
      { "cylinderType": "LPG_5KG",  "tier": "PREFERRED",   "bpclBaseRate": 445,   "tierMarkup": 35,   "customerPrice": 480 },
      { "cylinderType": "LPG_5KG",  "tier": "KEY_ACCOUNT", "bpclBaseRate": 445,   "tierMarkup": 25,   "customerPrice": 470 },
      { "cylinderType": "LPG_19KG", "tier": "STANDARD",    "bpclBaseRate": 1690,  "tierMarkup": 110,  "customerPrice": 1800 },
      { "cylinderType": "LPG_19KG", "tier": "PREFERRED",   "bpclBaseRate": 1690,  "tierMarkup": 80,   "customerPrice": 1770 },
      { "cylinderType": "LPG_19KG", "tier": "KEY_ACCOUNT", "bpclBaseRate": 1690,  "tierMarkup": 50,   "customerPrice": 1740 },
      { "cylinderType": "LPG_47_5KG_L", "tier": "STANDARD", "bpclBaseRate": 4225, "tierMarkup": 275, "customerPrice": 4500 },
      { "cylinderType": "LPG_47_5KG_V", "tier": "STANDARD", "bpclBaseRate": 4260, "tierMarkup": 275, "customerPrice": 4535 },
      { "cylinderType": "LPG_422KG_HIPPO", "tier": "STANDARD", "bpclBaseRate": 37550, "tierMarkup": 1450, "customerPrice": 39000 }
    ],
    "updatedBy": "Rajesh Verma", "updatedAt": "2026-06-01T09:30:00.000Z" }
]
```
(15 entries per month: 5 cylinders × 3 tiers.)

### 9.2 Update a price entry
| | |
|---|---|
| **Endpoint** | `PUT /pricing/months/{pricingMonthId}/entries` |
| **Auth** | Yes — `pricing.manage` (Manager, Accountant) |
| **Used by** | Pricing → Edit rate → **Save rate** · `pricingService.updatePriceEntry` |

**Request body — `UpdatePriceEntryRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| cylinderType | `CylinderTypeCode` | ✓ | |
| tier | `PricingTier` | ✓ | |
| bpclBaseRate | Money | ✓ | > 0 |
| tierMarkup | Money | ✓ | ≥ 0 |

`customerPrice = bpclBaseRate + tierMarkup` (GST-inclusive). Only `ACTIVE`/`DRAFT` months are editable.

**Response `200`** — full updated `PricingMonth` (with `updatedBy/updatedAt`).
```json
// request
{ "cylinderType": "LPG_19KG", "tier": "STANDARD", "bpclBaseRate": 1700, "tierMarkup": 110 }
```
**Errors:** `422` "Base rate must be positive and markup cannot be negative." · `409` "Archived pricing cannot be edited." · `404` month/entry.

---

## 10. Delivery & dispatch (merchant)

### 10.1 List delivery slips
| | |
|---|---|
| **Endpoint** | `GET /deliveries` |
| **Auth** | Yes — `delivery.view` |
| **Used by** | Delivery & Dispatch list · `deliveryService.listDeliveries` |

**Query** `status = SCHEDULED | DISPATCHED | DELIVERED | FAILED | ALL`, `search` (slip id, orderNumber, customerName, vehicleNumber).
**Response `200`** — `DeliverySlip[]` ordered DISPATCHED → SCHEDULED → FAILED → DELIVERED, then newest `scheduledDate`.
```json
[
  { "id": "DS-0148", "orderId": "ORD-2606-0148", "orderNumber": "ORD-2606-0148", "customerId": "CUST-001", "customerName": "Sharma General Store",
    "deliveryAddress": { "line1": "Shop 14, Sapna Sangeeta Road", "line2": "Near Bhawarkua Square", "city": "Indore", "state": "Madhya Pradesh", "pincode": "452001" },
    "deliverySiteName": "Registered delivery address",
    "items": [ { "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 4 }, { "cylinderType": "LPG_5KG", "cylinderLabel": "5 KG", "quantity": 6 } ],
    "itemsSummary": "4 × 19 KG · 6 × 5 KG", "cylindersAllocated": 10,
    "vehicleNumber": "MP09 GH 4521", "driverName": "Arjun Singh", "helperName": "Ramesh Kumar",
    "scheduledDate": "2026-06-15T09:00:00.000Z", "dispatchedAt": "2026-06-15T07:30:00.000Z",
    "emptiesCollected": 0, "pendingPickup": 4, "confirmationMethod": "OTP", "status": "DISPATCHED" }
]
```

### 10.2 Slip detail
| | |
|---|---|
| **Endpoint** | `GET /deliveries/{id}` |
| **Auth** | Yes — `delivery.view` |
| **Used by** | Delivery slip screen · `deliveryService.getDelivery` |

**Response `200`** — `DeliverySlip`. **Errors:** `404`.

### 10.3 Mark as dispatched
| | |
|---|---|
| **Endpoint** | `POST /deliveries/{id}/dispatch` |
| **Auth** | Yes — `delivery.confirm` (Manager, Godown Incharge) |
| **Used by** | Slip (SCHEDULED) → **Mark as Dispatched** · `deliveryService.dispatch` |

**Request** empty body.
**Backend rules (atomic):** slip must be `SCHEDULED` (`409`); for every line, `filled` stock ≥ quantity, else `409` "Not enough filled 19 KG in stock (3 available, 4 needed). Record a refill first." and **no** counts change; then write one `DISPATCHED` stock movement per line (`deltas.filled = −qty`, `referenceType: DELIVERY`), set slip `DISPATCHED` + `dispatchedAt`, order → `OUT_FOR_DELIVERY` (history note "Vehicle {vehicle} · {driver}"), notify customer "Order out for delivery".

**Response `200`** — updated `DeliverySlip`.

### 10.4 Confirm delivery
| | |
|---|---|
| **Endpoint** | `POST /deliveries/{id}/confirm` |
| **Auth** | Yes — `delivery.confirm` |
| **Used by** | Slip (DISPATCHED) → **Confirm Delivery** · `deliveryService.confirmDelivery` |

**Request body — `ConfirmDeliveryRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| otp | string | if `confirmationMethod = OTP` | 4 digits sent to the customer's mobile (mock accepts `4321`) |
| emptiesCollected | integer | ✓ | `0 ≤ n ≤ cylindersAllocated` |
| note | string | | |

**Backend rules:** slip must be `DISPATCHED` (`409` "already confirmed" / "not been dispatched yet"); validate OTP; set `DELIVERED`, `deliveredAt`, `emptiesCollected`, `pendingPickup = allocated − collected`; order → `DELIVERED`; write `EMPTIES_COLLECTED` movement (`deltas.empty = +n`); notify customer "Order delivered". (Invoice generation happens here or on dispatch — backend's choice; return `invoiceId` on the order.)

```json
// request
{ "otp": "4321", "emptiesCollected": 3, "note": "Left 1 empty for next visit" }
```
**Response `200`** — updated `DeliverySlip`.
**Errors:** `422 fieldErrors.otp` "Incorrect OTP" · `422 fieldErrors.emptiesCollected` "Invalid count" · `409` · `404`.

---

## 11. Warehouse inventory (merchant)

### 11.1 Inventory snapshot
| | |
|---|---|
| **Endpoint** | `GET /inventory` |
| **Auth** | Yes — `inventory.view` (Manager, Godown Incharge) |
| **Used by** | Warehouse Stock, Dashboard stock card · `inventoryService.getInventory` |

**Response `200`** — `InventorySnapshot`. Alerts are derived server-side from live counts (`filled < reorderThreshold` → WARNING, `< threshold/2` → CRITICAL; `damaged ≥ 5` → INFO).
```json
{
  "items": [
    { "cylinderType": "LPG_5KG",  "cylinderLabel": "5 KG",  "filled": 240, "empty": 118, "damaged": 4, "reorderThreshold": 150, "updatedAt": "2026-06-15T07:30:00.000Z" },
    { "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "filled": 186, "empty": 94,  "damaged": 7, "reorderThreshold": 120, "updatedAt": "2026-06-15T07:30:00.000Z" },
    { "cylinderType": "LPG_47_5KG_L", "cylinderLabel": "47.5 KG L", "filled": 42, "empty": 31, "damaged": 3, "reorderThreshold": 50, "updatedAt": "…" },
    { "cylinderType": "LPG_47_5KG_V", "cylinderLabel": "47.5 KG V", "filled": 58, "empty": 22, "damaged": 1, "reorderThreshold": 40, "updatedAt": "…" },
    { "cylinderType": "LPG_422KG_HIPPO", "cylinderLabel": "422 KG Hippo", "filled": 6, "empty": 4, "damaged": 1, "reorderThreshold": 4, "updatedAt": "…" }
  ],
  "alerts": [
    { "id": "SA-LOW-LPG_47_5KG_L", "cylinderType": "LPG_47_5KG_L", "severity": "WARNING", "message": "47.5 KG L filled stock (42) is below the reorder threshold (50)." },
    { "id": "SA-DMG-LPG_19KG", "cylinderType": "LPG_19KG", "severity": "INFO", "message": "7 damaged 19 KG cylinders awaiting return to BPCL." }
  ],
  "asOf": "2026-06-15T09:12:00.000Z"
}
```

### 11.2 Movement history
| | |
|---|---|
| **Endpoint** | `GET /inventory/movements` |
| **Auth** | Yes — `inventory.view` |
| **Used by** | Warehouse Stock → history with cylinder filter · `inventoryService.listMovements` |

**Query** `cylinderType = <code> | ALL`, `limit` (integer).
**Response `200`** — `StockMovement[]` newest first.
```json
[
  { "id": "SM-0118", "type": "DISPATCHED", "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 4, "deltas": { "filled": -4 }, "referenceType": "DELIVERY", "referenceId": "DS-0148", "recordedBy": "Mohan Lal", "recordedAt": "2026-06-15T07:30:00.000Z" },
  { "id": "SM-0117", "type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 60, "deltas": { "filled": 60 }, "referenceType": "CHALLAN", "referenceId": "BPCL/CH/22871", "note": "Morning refill truck", "recordedBy": "Mohan Lal", "recordedAt": "2026-06-15T06:50:00.000Z" },
  { "id": "SM-0113", "type": "MARKED_DAMAGED", "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 2, "deltas": { "empty": -2, "damaged": 2 }, "note": "Valve leak found during empties check", "recordedBy": "Mohan Lal", "recordedAt": "2026-06-14T08:40:00.000Z" }
]
```

### 11.3 Record a stock movement
| | |
|---|---|
| **Endpoint** | `POST /inventory/movements` |
| **Auth** | Yes — `inventory.adjust` (Manager, Godown Incharge) |
| **Used by** | Warehouse Stock → **Record Stock Movement** / per-card **Adjust** · `inventoryService.recordMovement` |

**Request body — `RecordStockMovementRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| type | `RECEIVED_FILLED` \| `SENT_TO_PLANT` \| `MARKED_DAMAGED` \| `CORRECTION` | ✓ | `DISPATCHED`/`EMPTIES_COLLECTED` are **rejected** here (system-generated) |
| cylinderType | `CylinderTypeCode` | ✓ | |
| quantity | integer ≥1 | for first three types | |
| fromBucket | `StockBucket` | SENT_TO_PLANT / MARKED_DAMAGED | SENT_TO_PLANT: `empty`\|`damaged`; MARKED_DAMAGED: `filled`\|`empty` |
| bucket | `StockBucket` | CORRECTION | Count being corrected |
| newCount | integer ≥0 | CORRECTION | New physical count |
| note | string | CORRECTION (required) | Audit reason; optional otherwise |
| referenceId | string | | Challan / vehicle no. for plant movements |

**Effect on counts**
| type | deltas |
|---|---|
| RECEIVED_FILLED | `filled +qty` |
| SENT_TO_PLANT | `fromBucket −qty` |
| MARKED_DAMAGED | `fromBucket −qty`, `damaged +qty` |
| CORRECTION | `bucket += (newCount − current)` |

No bucket may go negative (`409`). Response is the created movement; the app then refetches `/inventory`.

```json
// request — refill truck
{ "type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 60, "referenceId": "BPCL/CH/22871", "note": "Morning refill truck" }
// request — damaged
{ "type": "MARKED_DAMAGED", "cylinderType": "LPG_19KG", "quantity": 2, "fromBucket": "empty", "note": "Valve leak" }
// request — correction
{ "type": "CORRECTION", "cylinderType": "LPG_5KG", "bucket": "filled", "newCount": 237, "note": "Physical audit: 3 short vs register" }
// response 201
{ "id": "SM-0119", "type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "cylinderLabel": "19 KG", "quantity": 60, "deltas": { "filled": 60 },
  "note": "Morning refill truck", "referenceType": "CHALLAN", "referenceId": "BPCL/CH/22871", "recordedBy": "Mohan Lal", "recordedAt": "2026-06-15T09:12:00.000Z" }
```
**Errors (`422` with `fieldErrors`):** `quantity` "Enter at least 1" / "Max 94" · `fromBucket` "Required" · `bucket` "Required" · `newCount` "Enter a count of 0 or more" / "No change" · `note` "Reason required" · `409` negative stock.

---

## 12. Payments & invoices

### 12.1 Customer payment summary
| | |
|---|---|
| **Endpoint** | `GET /customers/{customerId}/payments/summary` |
| **Auth** | Yes — customer (own) or staff `payments.view` |
| **Used by** | Customer Payments tab header, Customer dashboard · `paymentService.getCustomerPaymentSummary` |

**Response `200`** — `CustomerPaymentSummary`
```json
{ "totalInvoiced": 14940, "totalPaid": 11400, "runningBalance": 3540, "overdueAmount": 0, "lastPaymentAt": "2026-06-11T14:25:00.000Z" }
```
`overdueAmount` = Σ balance of invoices with `dueAt < now`. INVALID payments are excluded from `lastPaymentAt`.

### 12.2 List invoices
| | |
|---|---|
| **Endpoint** | `GET /invoices` |
| **Auth** | Yes — customer (own) or staff `payments.view` |
| **Used by** | Customer Payments (invoice list), Record Payment invoice picker · `paymentService.listInvoices` |

**Query** `customerId`, `openOnly=true` (balance > 0).
**Response `200`** — `Invoice[]` newest `issuedAt` first.
```json
[
  { "id": "INV-0144", "invoiceNumber": "MBGA/INV/0144", "orderId": "ORD-2606-0144", "orderNumber": "ORD-2606-0144",
    "customerId": "CUST-006", "customerName": "Annapurna Sweets & Namkeen",
    "amount": 7500, "gstPercent": 18, "gstAmount": 1350, "totalAmount": 8850, "paidAmount": 0, "balance": 8850, "status": "UNPAID",
    "issuedAt": "2026-06-13T18:00:00.000Z", "dueAt": "2026-06-20T18:00:00.000Z", "isGstInvoice": false }
]
```

### 12.3 List payments
| | |
|---|---|
| **Endpoint** | `GET /payments` |
| **Auth** | Yes — customer (own) or staff `payments.view` |
| **Used by** | Customer Payments history, Merchant Payments · `paymentService.listPayments` |

**Query** `customerId`, `reconciliationStatus = PENDING | RECONCILED | INVALID | ALL`, `search` (payment id, invoiceNumber, customerName, reference).
**Response `200`** — `Payment[]` newest `paidAt` first.
```json
[
  { "id": "PAY-0211", "invoiceId": "INV-0141", "invoiceNumber": "MBGA/INV/0141", "customerId": "CUST-001", "customerName": "Sharma General Store",
    "invoiceAmount": 5400, "amountCollected": 5400, "mode": "UPI", "paidAt": "2026-06-11T14:25:00.000Z", "reference": "UPI-4471820039",
    "reconciliationStatus": "RECONCILED", "collectedBy": "Sunita Joshi", "customerRunningBalance": 3540 },
  { "id": "PAY-0205", "invoiceId": "INV-0132", "invoiceNumber": "MBGA/INV/0132", "customerId": "CUST-002", "customerName": "Apex Foods Pvt Ltd",
    "invoiceAmount": 35000, "amountCollected": 35000, "mode": "NEFT", "paidAt": "2026-06-12T11:00:00.000Z", "reference": "NEFT-HDFC-88213",
    "reconciliationStatus": "INVALID", "invalidReason": "UTR not found in bank statement", "collectedBy": "Sunita Joshi", "customerRunningBalance": 41300 }
]
```

### 12.4 Payment detail
| | |
|---|---|
| **Endpoint** | `GET /payments/{id}` |
| **Auth** | Yes |
| **Used by** | Payment detail sheet · `paymentService.getPayment` |

**Response `200`** — `Payment`. **Errors:** `404`.

### 12.5 Record a payment
| | |
|---|---|
| **Endpoint** | `POST /payments` |
| **Auth** | Yes — `payments.record` (Manager, Accountant) |
| **Used by** | Merchant Payments → **Record payment** · `paymentService.recordPayment` |

**Request body — `RecordPaymentRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| invoiceId | string | ✓ | Must be open (balance > 0) |
| amount | Money | ✓ | > 0 and ≤ invoice balance |
| mode | `PaymentMode` | ✓ | |
| reference | string | UPI/NEFT | Required for non-cash |
| paidAt | ISO date | ✓ | |

**Backend rules:** update invoice `paidAmount/balance/status`; `reconciliationStatus = RECONCILED` for CASH, `PENDING` for UPI/NEFT; recompute `customer.runningBalance`; notify customer "Payment received".

**Response `201`** — `Payment`.
```json
// request
{ "invoiceId": "INV-0144", "amount": 5000, "mode": "UPI", "reference": "UPI-9912003311", "paidAt": "2026-06-15T09:12:00.000Z" }
// response
{ "id": "PAY-0213", "invoiceId": "INV-0144", "invoiceNumber": "MBGA/INV/0144", "customerId": "CUST-006", "customerName": "Annapurna Sweets & Namkeen",
  "invoiceAmount": 8850, "amountCollected": 5000, "mode": "UPI", "paidAt": "2026-06-15T09:12:00.000Z", "reference": "UPI-9912003311",
  "reconciliationStatus": "PENDING", "collectedBy": "Sunita Joshi", "customerRunningBalance": 3850 }
```
**Errors:** `422 fieldErrors.amount` "Enter a valid amount" / "Exceeds balance" · `422 fieldErrors.reference` "Reference is required" · `404` invoice.

---

## 13. Expenses (merchant)

### 13.1 List expenses
| | |
|---|---|
| **Endpoint** | `GET /expenses` |
| **Auth** | Yes — `expenses.view` (Manager, Accountant) |
| **Used by** | Expenses screen · `expenseService.listExpenses` |

**Query** `period = YYYY-MM | ALL`, `category = ExpenseCategory | ALL`.
**Response `200`** — `Expense[]` newest `date` first.
```json
[
  { "id": "EXP-0312", "category": "FUEL", "amount": 4200, "date": "2026-06-15T08:00:00.000Z", "enteredBy": "Mohan Lal", "reportPeriod": "2026-06", "note": "Diesel — MP09 GH 4521" },
  { "id": "EXP-0311", "category": "VEHICLE_MAINTENANCE", "amount": 12500, "date": "2026-06-12T10:00:00.000Z", "enteredBy": "Mohan Lal", "reportPeriod": "2026-06", "note": "Brake service — MP09 HT 7730" }
]
```

### 13.2 Add expense
| | |
|---|---|
| **Endpoint** | `POST /expenses` |
| **Auth** | Yes — `expenses.add` |
| **Used by** | Expenses → **Add expense** · `expenseService.addExpense` |

**Request body — `CreateExpenseRequest`**
| Field | Type | Req | Rules |
|---|---|:-:|---|
| category | `ExpenseCategory` | ✓ | |
| amount | Money | ✓ | > 0 |
| date | ISO date | ✓ | App sends today |
| note | string | | |

**Response `201`** — `Expense` (`reportPeriod = date.slice(0,7)`).
```json
// request
{ "category": "FUEL", "amount": 1500, "date": "2026-06-15T09:12:00.000Z", "note": "Diesel" }
// response
{ "id": "EXP-0313", "category": "FUEL", "amount": 1500, "date": "2026-06-15T09:12:00.000Z", "enteredBy": "Rajesh Verma", "reportPeriod": "2026-06", "note": "Diesel" }
```
**Errors:** `422 fieldErrors.amount` "Enter a valid amount" · `422 fieldErrors.category`.

---

## 14. Reports (merchant)

### 14.1 Get report
| | |
|---|---|
| **Endpoint** | `GET /reports/{type}?from=&to=` |
| **Auth** | Yes — `reports.view` (Manager, Accountant) |
| **Used by** | Reports screen (4 report tabs, date range) · `reportService.getReport` |

**Path** `type ∈ DAILY_DELIVERY | PAYMENT_COLLECTION | PENDING_PICKUP | EXPENSE`. **Query** `from`, `to` (ISO dates, inclusive).

**Response `200`** — `Report`. The table renders whatever `columns/rows` come back; values may be pre-formatted strings (`"₹4,200"`, `"15 Jun 2026"`). Each row **must** have an `id`.

| type | summary items | columns |
|---|---|---|
| DAILY_DELIVERY | Deliveries, Delivered, Cylinders, Empties collected | slip, customer, qty (right), status |
| PAYMENT_COLLECTION | Collected, Cash, UPI, NEFT (exclude INVALID) | date, customer, mode, amount (right), status |
| PENDING_PICKUP | Customers, Cylinders pending | customer, cylinder, pending (right), since |
| EXPENSE | Total expenses, Entries, Largest category | date, category, by, amount (right) |

```json
{
  "type": "PAYMENT_COLLECTION", "title": "Payment Collection Report",
  "period": { "from": "2026-06-01T00:00:00.000Z", "to": "2026-06-15T23:59:59.000Z" },
  "summary": [ { "label": "Collected", "value": "₹1,42,640" }, { "label": "Cash", "value": "₹28,000" }, { "label": "UPI", "value": "₹79,640" }, { "label": "NEFT", "value": "₹35,000" } ],
  "columns": [ { "key": "date", "label": "Date" }, { "key": "customer", "label": "Customer" }, { "key": "mode", "label": "Mode" }, { "key": "amount", "label": "Amount", "align": "right" }, { "key": "status", "label": "Status" } ],
  "rows": [ { "id": "PAY-0211", "date": "11 Jun 2026", "customer": "Sharma General Store", "mode": "UPI", "amount": "₹5,400", "status": "Reconciled" } ],
  "generatedAt": "2026-06-15T09:12:00.000Z"
}
```

---

## 15. Notifications

The user is inferred from the token. Customers get their own bucket; all staff share the merchant bucket (per-branch later).

### 15.1 List
| | |
|---|---|
| **Endpoint** | `GET /notifications` |
| **Auth** | Yes |
| **Used by** | Notifications screen, bell badge (unread count) · `notificationService.list` |

**Response `200`** — `AppNotification[]` newest first.
```json
[
  { "id": "NTF-M-1", "title": "Stock below reorder threshold", "message": "47.5 KG filled stock is 42 against a threshold of 50. Plan a BPCL refill.", "severity": "CRITICAL", "category": "STOCK", "createdAt": "2026-06-15T07:32:00.000Z", "read": false },
  { "id": "NTF-M-2", "title": "Orders awaiting confirmation", "message": "1 new order (ORD-2606-0150, Hotel Blue Orchid) is waiting to be confirmed.", "severity": "WARNING", "category": "ORDER", "createdAt": "2026-06-15T08:00:00.000Z", "read": false, "referenceType": "ORDER", "referenceId": "ORD-2606-0150" }
]
```

### 15.2 Detail — `GET /notifications/{id}` → `AppNotification` (`404`).
### 15.3 Mark read — `POST /notifications/{id}/read` → `204`.
### 15.4 Mark all read — `POST /notifications/read-all` → `204`.

---

## 16. Merchant dashboard

| | |
|---|---|
| **Endpoint** | `GET /dashboard/merchant` |
| **Auth** | Yes — `dashboard.view` |
| **Used by** | Merchant Dashboard tab · `dashboardService.getMerchantDashboard` |

**Response `200`** — `MerchantDashboard`
```json
{
  "kpis": {
    "totalCustomers": 10, "pendingVerification": 2,
    "totalOrders": 14, "outForDelivery": 2, "todaysOrders": 3, "pendingOrders": 1, "readyForDispatch": 3, "deliveriesToday": 2,
    "pendingPaymentsAmount": 87640, "pendingPaymentsCount": 3, "pendingPickups": 6,
    "filledStock": 532, "emptyStock": 269, "damagedStock": 16, "pendingKyc": 2
  },
  "alerts": [ { "id": "NTF-M-1", "title": "Stock below reorder threshold", "severity": "CRITICAL", "category": "STOCK", "message": "…", "createdAt": "…", "read": false } ],
  "recentOrders": [ { "id": "ORD-2606-0150", "...": "Order" } ],
  "recentRegistrations": [ { "id": "KYC-003", "...": "KycApplication" } ],
  "asOf": "2026-06-15T09:12:00.000Z"
}
```
KPI definitions: `pendingOrders` = status PLACED · `readyForDispatch` = CONFIRMED + PREPARING · `outForDelivery` = slips DISPATCHED ·
`deliveriesToday` = slips DISPATCHED or delivered today · `pendingPaymentsAmount/Count` = open invoices · `pendingPickups` = Σ slip.pendingPickup ·
`*Stock` = Σ across cylinder types · `pendingKyc = pendingVerification` = PENDING applications. `alerts` = up to 4 unread non-INFO merchant notifications.

---

## 17. Document upload (new, Phase 2)

The mock only records a file name. For the real API the app will call these before registration / when viewing KYC documents.

### 17.1 Upload a KYC document
| | |
|---|---|
| **Endpoint** | `POST /documents` (multipart/form-data) |
| **Auth** | Yes (customer `NEW`/`PENDING` or staff `customers.create`) |

**Form fields** `file` (PDF/JPG/PNG, ≤ 5 MB), `type` (`KycDocumentType`).
**Response `201`** `{ "fileId": "doc_01HZX…", "fileName": "aadhaar_front.jpg", "contentType": "image/jpeg", "size": 348211 }` — the app puts `fileId` into `documents[].fileName` of §5.1 / §7.1.
**Errors:** `413` too large · `415` unsupported type.

### 17.2 Get a secure download URL
| | |
|---|---|
| **Endpoint** | `GET /documents/{fileId}/url` |
| **Auth** | Yes — owner or `customers.kyc.review` |

**Response `200`** `{ "url": "https://…signed…", "expiresInSeconds": 300 }` — used by the "view document" button on the KYC review screen.

---

## 18. Business rules the backend must enforce

### 18.1 GST (inclusive)
`unitPrice` = `PriceEntry.customerPrice` for the customer's tier in the ACTIVE month — already includes 18 % GST.
`totalAmount = Σ unitPrice × quantity` · `subtotal = round(totalAmount / 1.18)` · `gstAmount = totalAmount − subtotal`.
Example: 1 × 19 KG @ ₹1,800 → total 1800, subtotal 1525, GST 275.

### 18.2 Who may order
Only customers with `accountStatus = APPROVED` and `kycStatus = VERIFIED`. Industrial orders need `deliverySiteId`.

### 18.3 Cylinder catalogue & quantity limits (per order line)
| Code | Label | Industrial only | min–max qty |
|---|---|:-:|---|
| LPG_5KG | 5 KG | | 1–100 |
| LPG_19KG | 19 KG | | 1–50 |
| LPG_47_5KG_L | 47.5 KG L (liquid) | | 1–30 |
| LPG_47_5KG_V | 47.5 KG V (vapour) | | 1–30 |
| LPG_422KG_HIPPO | 422 KG Hippo | ✓ | 1–5 |

### 18.4 Cut-off
16:00 IST. Before → `scheduledDeliveryDate` = tomorrow 09:00, slot "09:00 AM – 01:00 PM". After → day after tomorrow, slot "02:00 PM – 06:00 PM".

### 18.5 KYC
Retail: AADHAAR (12 digits) + PAN (`^[A-Z]{5}\d{4}[A-Z]$`). Industrial: FSSAI (14 digits) + GST (`^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`, becomes `customer.gstin`).
Store full numbers encrypted; **return masked only**. Decision flips customer + user status and notifies the customer.

### 18.6 Stock
Every count change is a `StockMovement`; counts and ledger must always agree. Dispatch is atomic across lines and fails without touching counts if any line is short. Alerts are derived from live counts.

### 18.7 Payments
Cash → RECONCILED; UPI/NEFT → PENDING until bank match (reconciliation UI is backend/admin-side; the app only displays `reconciliationStatus` and `invalidReason`). `customer.runningBalance` = Σ open invoice balances. Industrial invoices are GST invoices (`isGstInvoice`, `gstin`).

### 18.8 Notifications generated by the backend
| Event | To | Title |
|---|---|---|
| Registration / staff-added customer | customer · merchant | "Application received" · "New KYC application" |
| KYC approved / rejected | customer | "Account approved" · "Application rejected" (CRITICAL) |
| Order created | customer · merchant | "Order placed" · "New order received" (WARNING) |
| Dispatch | customer | "Order out for delivery" |
| Delivery confirmed | customer | "Order delivered" |
| Payment recorded | customer | "Payment received" |
| Stock below threshold | merchant | "Stock below reorder threshold" (CRITICAL/WARNING) |

---

## 19. Endpoint index

| # | Method | Path | Auth / permission | Frontend service |
|---|---|---|---|---|
| 1 | POST | `/auth/otp/send` | — | `authService.sendOtp` |
| 2 | POST | `/auth/otp/verify` | — | `authService.verifyOtp` |
| 3 | POST | `/auth/otp/resend` | — | `authService.resendOtp` |
| 4 | GET | `/auth/me` | token | `authService.restoreSession` |
| 5 | POST | `/auth/logout` | token | `authService.logout` |
| 6 | POST | `/customers/register` | customer (NEW) | `customerService.register` |
| 7 | GET | `/customers/me` | customer | `customerService.getMyProfile` |
| 8 | GET | `/dashboard/customer` | customer | `dashboardService.getCustomerDashboard` |
| 9 | GET | `/pricing/customers/{customerId}` | customer / `pricing.view` | `pricingService.getCustomerPricing` |
| 10 | GET | `/orders/statuses` | token | `orderService.getOrderStatuses` |
| 11 | GET | `/orders/cutoff` | token | `orderService.getCutoffInfo` |
| 12 | POST | `/orders/quote` | customer / `orders.create` | `orderService.getQuote` |
| 13 | POST | `/orders` | customer / `orders.create` | `orderService.createOrder` |
| 14 | GET | `/orders` | customer / `orders.view` | `orderService.listOrders` |
| 15 | GET | `/orders/{id}` | owner / `orders.view` | `orderService.getOrder` |
| 16 | POST | `/customers` | `customers.create` | `customerService.createByStaff` |
| 17 | GET | `/customers` | `customers.view` | `customerService.listCustomers` |
| 18 | GET | `/customers/{id}` | `customers.view` | `customerService.getCustomer` |
| 19 | GET | `/customers/{id}/eligibility` | `orders.create` | `customerService.checkEligibility` |
| 20 | GET | `/kyc/applications` | `customers.kyc.review` | `customerService.listKycApplications` |
| 21 | GET | `/kyc/applications/{id}` | `customers.kyc.review` | `customerService.getKycApplication` |
| 22 | POST | `/kyc/applications/{id}/decision` | `customers.kyc.review` | `customerService.decideKyc` |
| 23 | GET | `/pricing/months` | `pricing.view` | `pricingService.getPricingMonths` |
| 24 | PUT | `/pricing/months/{id}/entries` | `pricing.manage` | `pricingService.updatePriceEntry` |
| 25 | GET | `/deliveries` | `delivery.view` | `deliveryService.listDeliveries` |
| 26 | GET | `/deliveries/{id}` | `delivery.view` | `deliveryService.getDelivery` |
| 27 | POST | `/deliveries/{id}/dispatch` | `delivery.confirm` | `deliveryService.dispatch` |
| 28 | POST | `/deliveries/{id}/confirm` | `delivery.confirm` | `deliveryService.confirmDelivery` |
| 29 | GET | `/inventory` | `inventory.view` | `inventoryService.getInventory` |
| 30 | GET | `/inventory/movements` | `inventory.view` | `inventoryService.listMovements` |
| 31 | POST | `/inventory/movements` | `inventory.adjust` | `inventoryService.recordMovement` |
| 32 | GET | `/customers/{id}/payments/summary` | customer / `payments.view` | `paymentService.getCustomerPaymentSummary` |
| 33 | GET | `/invoices` | customer / `payments.view` | `paymentService.listInvoices` |
| 34 | GET | `/payments` | customer / `payments.view` | `paymentService.listPayments` |
| 35 | GET | `/payments/{id}` | customer / `payments.view` | `paymentService.getPayment` |
| 36 | POST | `/payments` | `payments.record` | `paymentService.recordPayment` |
| 37 | GET | `/expenses` | `expenses.view` | `expenseService.listExpenses` |
| 38 | POST | `/expenses` | `expenses.add` | `expenseService.addExpense` |
| 39 | GET | `/reports/{type}` | `reports.view` | `reportService.getReport` |
| 40 | GET | `/notifications` | token | `notificationService.list` |
| 41 | GET | `/notifications/{id}` | token | `notificationService.get` |
| 42 | POST | `/notifications/{id}/read` | token | `notificationService.markRead` |
| 43 | POST | `/notifications/read-all` | token | `notificationService.markAllRead` |
| 44 | GET | `/dashboard/merchant` | `dashboard.view` | `dashboardService.getMerchantDashboard` |
| 45 | POST | `/documents` | customer / `customers.create` | *(new — replaces mock `attachDocument`)* |
| 46 | GET | `/documents/{fileId}/url` | owner / `customers.kyc.review` | *(new — KYC "view document")* |

---

*Generated from the Phase 1 frontend contracts. Keep this file and `shared/types/*.ts` in sync; when the backend
publishes its final paths, update the `Endpoint` column here and in `API_INTEGRATION.md`'s mapping table.*
