# Credit limit enforcement fix

## What changed

Credit-limit enforcement now runs for **every new order**, irrespective of who placed it:

- Customer app
- Merchant app / merchant staff
- Admin web panel
- Repeat and reorder flows (they already route through the same create method)

The only approved exception is an unexpired, unused `CreditOverrideAudit` record. This makes every over-limit exception explicit and auditable.

## Not changed

- Existing orders are not cancelled retroactively.
- Doorstep order amendments were already checked and remain checked.
- A credit limit is active only when both global `credit_limit_enabled` and that customer's `credit_enabled` are true, with a positive `credit_limit`.

## Deploy

This is application-code only: no database migration is required.

```bash
cd ~/mbga-backend/backend && \
tar czf ~/backup-before-credit-enforcement-$(date +%F-%H%M).tar.gz app/modules/orders/service.py && \
unzip -o ./mbga-credit-limit-enforcement-fix-20261012.zip && \
./venv/bin/python -c "import app.main; print('Credit enforcement imports OK')" && \
sudo systemctl restart mbga-backend && \
sleep 5 && \
curl -fsS http://127.0.0.1:8000/health
```
