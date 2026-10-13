# Postal Address and Vehicle Coverage Deployment

This update imports the India Post directory, resolves a customer's six-digit pincode into
state/district/post-office options, maps merchant vehicles to pincodes, and prevents a mapped
merchant from assigning a vehicle outside its configured delivery area.

## Deploy

Run from `/home/ubuntu/mbga-backend/backend` after uploading the ZIP into that directory:

```bash
cd ~/mbga-backend/backend && \
tar czf ~/backup-before-postal-vehicle-$(date +%F-%H%M).tar.gz app database scripts && \
unzip -o ./mbga-postal-vehicle-coverage-20261013.zip && \
./venv/bin/python -m alembic upgrade head && \
./venv/bin/python scripts/import_postal_locations.py data/india-post-pincodes.csv && \
./venv/bin/python -c "import app.main; print('Postal vehicle imports OK')" && \
sudo systemctl restart mbga-backend && \
sleep 5 && \
sudo systemctl is-active mbga-backend && \
curl -fsS http://127.0.0.1:8000/health
```

The importer is safe to run again. Existing `(pincode, office)` rows are updated instead of
duplicated.

## App/API flow

1. Customer enters a pincode:
   `GET /api/v1/customer/locations/pincodes/{pincode}`.
2. The app fills state and district and lets the customer select one returned post office.
3. Merchant/admin maps a vehicle with:
   `PUT /api/v1/merchant/vehicles/{vehicleId}/pincodes` or the matching admin endpoint.
4. Before order confirmation, fetch eligible vehicles with:
   `GET /api/v1/merchant/orders/{orderId}/available-vehicles`.
5. After a delivery exists, the same list is available at:
   `GET /api/v1/merchant/deliveries/{deliveryId}/available-vehicles`.
6. Existing confirm/reassign endpoints reject a vehicle that is not mapped to the customer's
   pincode.

Example mapping payload:

```json
{
  "pincodes": ["122001", "122018"]
}
```

Admin may also upload a refreshed CSV through
`POST /api/v1/admin/postal-locations/import` using multipart field `upload`.

## Safe rollout

Merchants with no vehicle-pincode mappings keep the previous assignment behaviour. As soon as
the first mapping is configured for a merchant, coverage enforcement turns on for that merchant.
This avoids blocking current production deliveries while mappings are being prepared.
