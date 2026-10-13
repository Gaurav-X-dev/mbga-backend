# Credit Limit deployment

The migration installs this feature in a safe state: the global feature flag and reminders are
both OFF. Existing customers have credit disabled with a zero limit.

## Enforced paths

- Customer `POST /api/v1/customer/orders`
- Customer `POST /api/v1/customer/orders/repeat`
- Customer `POST /api/v1/customer/orders/{orderId}/reorder`
- Delivery Partner `PUT /api/v1/delivery/deliveries/{deliveryId}/update-items`

Merchant and Admin order creation remain unblocked.

## Admin endpoints

- `GET|PATCH /api/v1/admin/credit/settings`
- `GET /api/v1/admin/credit/customers`
- `PATCH /api/v1/admin/credit/customers/{customerId}`
- `POST /api/v1/admin/credit/customers/{customerId}/overrides`
- `GET /api/v1/admin/credit/customers/{customerId}/history`
- `PATCH /api/v1/merchant/credit/customers/{customerId}` (tenant-scoped)

Merchant managers can update only customers owned by their merchant. Customer profile and
merchant customer responses expose the credit terms and live usage as read-only fields.

Permissions are `credit.view`, `credit.manage`, and `credit.override`. Run `scripts/seed_rbac.py`
after migration so the permissions exist and the Super Admin role receives them.

## Production activation order

1. Deploy code, upgrade the database, seed RBAC, and restart the backend.
2. Install and start the supplied systemd timer.
3. Configure a small set of test customers through the Admin API.
4. Turn on `creditLimitEnabled` only after those customer limits have been verified.
5. Turn on `remindersEnabled` separately after checking the reminder template and quiet hours.

Never enable the global flag before customer limits have been reviewed.

## Rollback

The immediate no-data-loss rollback is `PATCH /api/v1/admin/credit/settings` with
`{"creditLimitEnabled":false,"remindersEnabled":false}` and stopping the timer. Code can then be
rolled back while leaving migration `20261010_0040` in place. Downgrade the migration only when
the credit audit/history data may be deleted.
