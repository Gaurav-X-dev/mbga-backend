# Dynamic UPI QR API: Deployment and Verification

This patch updates the existing Delivery App endpoint:

```http
POST /api/v1/delivery/deliveries/{deliveryId}/generate-qr
```

It accepts `orderId`, `amount`, and optional `notes`, then reads `upiId` and `payeeName` from the
assigned merchant's database configuration and
returns a real 300×300 PNG as raw Base64. It does not use a payment gateway and does not save a
QR/payment record in the database.

## Deploy

Run these commands from the backend directory on the server:

```bash
cd ~/mbga-backend/backend

tar czf ~/backup-code-$(date +%F-%H%M).tar.gz app docs pyproject.toml requirements.txt

unzip -o mbga-upi-qr-complete-20261006.zip

./venv/bin/pip install -r requirements.txt

./venv/bin/alembic upgrade head

find app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

./venv/bin/python -c "import qrcode, PIL; import app.main; print('QR dependency and backend imports OK')"

sudo systemctl restart mbga-backend
sleep 5
curl -s http://127.0.0.1:8000/health
```

Expected health response:

```json
{"status":"ok"}
```

## Verify the OpenAPI contract

```bash
curl -s http://127.0.0.1:8000/openapi/delivery.json | ./venv/bin/python -c '
import json, sys
d = json.load(sys.stdin)
op = d["paths"]["/api/v1/delivery/deliveries/{deliveryId}/generate-qr"]["post"]
schemas = d["components"]["schemas"]
req = op["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
res = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
print("summary:", op["summary"])
print("request:", list(schemas[req]["properties"]))
print("required:", schemas[req].get("required"))
print("response:", list(schemas[res]["properties"]))
'
```

Expected important fields:

```text
request: orderId, amount, notes
required: orderId, amount
response: ... upiString, qrCodeBase64, mimeType
```

## Call the API

Replace the token, delivery id and order id with live values:

```bash
export ACCESS_TOKEN='delivery-app-access-token'
export DELIVERY_ID='delivery-uuid'
export ORDER_ID='order-uuid'

curl -s -X POST \
  "http://127.0.0.1:8000/api/v1/delivery/deliveries/${DELIVERY_ID}/generate-qr" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"orderId\":\"${ORDER_ID}\",\"amount\":3200.50,\"notes\":\"Order at Gate 2\"}" \
  > /tmp/upi-qr-response.json

./venv/bin/python -c '
import base64, json
d = json.load(open("/tmp/upi-qr-response.json"))
d = d.get("data", d)
raw = base64.b64decode(d["qrCodeBase64"], validate=True)
assert raw.startswith(b"\x89PNG\r\n\x1a\n")
open("/tmp/upi-qr.png", "wb").write(raw)
print("PNG OK:", len(raw), "bytes")
print("UPI:", d["upiString"])
print("Saved: /tmp/upi-qr.png")
'
```

The Delivery App obtains both ids from `GET /api/v1/delivery/deliveries/today`: use `id` as
`DELIVERY_ID`, `orderId` as `ORDER_ID`, and `billing.totalPayableAmount` as the QR amount.

## Database behavior

The QR endpoint reads the assigned delivery slip to verify the driver, delivery state and
`orderId`, and reads the merchant's configured payee values. It writes nothing to the database.
Specifically, it does not persist a per-request copy of:

- `upiId`
- `payeeName`
- `amount`
- `notes`
- `upiString`
- PNG/Base64 data
- payment success or failure

Actual payment rows are created only by the separate Merchant Payment API. The merchant UPI fields
are added by migration `20261006_0028`.

Before using QR for a merchant, configure its payee values (replace all placeholders):

```sql
UPDATE merchants
SET upi_id = 'merchant@bank',
    upi_payee_name = 'Merchant Display Name'
WHERE id = 'merchant-uuid';
```

If either value is absent, the QR endpoint returns `409 MERCHANT_UPI_NOT_CONFIGURED`.
