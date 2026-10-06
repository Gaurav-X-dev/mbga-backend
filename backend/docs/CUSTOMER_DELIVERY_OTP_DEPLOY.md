# Customer Delivery OTP: API, App Integration and Deployment

## What was wrong

The backend already created a four-digit OTP when the driver marked a delivery out for delivery.
It saved a verification hash and put the OTP in the customer's `DELIVERY_DISPATCHED` notification.
But Customer Order APIs had no OTP field. If push was disabled, the device token was missing, or
the app was reopened, the Customer App could not reliably display the code.

## Final customer contract

No new endpoint is required. Both existing Customer Order endpoints now return `deliveryOtp`:

```http
GET /api/v1/customer/orders
GET /api/v1/customer/orders/{orderId}
Authorization: Bearer <customer-access-token>
```

Active delivery example:

```json
{
  "id": "order-uuid",
  "orderNumber": "ORD-2610-0042",
  "status": "OUT_FOR_DELIVERY",
  "deliverySlipId": "delivery-uuid",
  "deliveryOtp": "1234"
}
```

Customer App rules:

1. When status is `OUT_FOR_DELIVERY` or `ON_LOCATION` and `deliveryOtp` is non-null, show it
   prominently with: **Share this OTP with the driver only after receiving the cylinders.**
2. Refresh order detail after `DELIVERY_DISPATCHED` and `DELIVERY_ON_LOCATION_CUSTOMER`.
3. Read `deliveryOtp` again whenever the tracking screen opens; push notification text is only an
   alert, not the source of truth.
4. Hide the OTP when the field is null. It becomes null after `DELIVERED` or failed/cancelled.
5. Never use Delivery App's `devConfirmationCode`; it is disabled in production.

The endpoint remains customer-scoped. A customer cannot read another customer's order. Merchant
Order APIs serialize `deliveryOtp` as null and Delivery App APIs do not expose the field.

## Storage and security

- `confirmation_code_hash` is still used to verify the OTP.
- `confirmation_code_encrypted` temporarily stores a reversible encrypted copy so the owning
  customer's API can recover it after refresh.
- The plain OTP is never stored in the delivery slip table.
- Encryption uses a purpose-specific key derived from `DOCUMENT_ENCRYPTION_SECRET` (falling back
  to the JWT signing secret when that setting is absent). Keep that secret stable across restarts.
- Both hash and encrypted copy are erased after successful delivery or failed/cancelled delivery.
- Orders already dispatched before this release are not backfilled. Their earlier notification is
  still available, but newly dispatched deliveries receive the reliable `deliveryOtp` field.

## Database changes

Two migrations are included:

- `20261006_0027`: adds `delivery_slips.confirmation_code_encrypted`.
- `20261006_0028`: adds the two merchant UPI columns used by the already-deployed QR feature. This
  closes a previous model/schema gap and safely skips columns that were manually added already.

## Deploy

Run from the backend directory on the server:

```bash
cd ~/mbga-backend/backend

tar czf ~/backup-code-$(date +%F-%H%M).tar.gz app database docs tests

unzip -o mbga-customer-delivery-otp-20261006.zip

./venv/bin/alembic upgrade head
./venv/bin/python -c "import app.main; print('imports OK')"

find app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

sudo systemctl restart mbga-backend
sleep 5
curl -s http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

Confirm migration state:

```bash
./venv/bin/alembic current
```

Expected revision: `20261006_0028 (head)`.

## Verify the API

Use a customer token and one of that customer's orders currently out for delivery:

```bash
export CUSTOMER_TOKEN='customer-access-token'
export ORDER_ID='order-uuid'

curl -s \
  "http://127.0.0.1:8000/api/v1/customer/orders/${ORDER_ID}" \
  -H "Authorization: Bearer ${CUSTOMER_TOKEN}" \
  | ./venv/bin/python -c '
import json, sys
d = json.load(sys.stdin)
print("status:", d["status"])
print("deliveryOtp:", d.get("deliveryOtp"))
'
```

Expected while active: a four-digit `deliveryOtp`. After the driver successfully verifies it,
repeat the call and expect `deliveryOtp: None`.

Database check without printing the secret values:

```sql
SELECT
  id,
  status,
  confirmation_code_hash IS NOT NULL AS has_otp_hash,
  confirmation_code_encrypted IS NOT NULL AS has_encrypted_otp
FROM delivery_slips
WHERE id = 'delivery-uuid';
```

Expected during delivery: both flags are `1`. Expected after delivered/failed: both are `0`.

## Notification check

The existing notification remains unchanged. At out-for-delivery the customer receives a
`DELIVERY_DISPATCHED` notification whose message includes the same OTP. Push delivery still
requires Customer App FCM configuration and a live customer session with a push token. Even if
push is missed, the order endpoint above continues to provide the active OTP.
