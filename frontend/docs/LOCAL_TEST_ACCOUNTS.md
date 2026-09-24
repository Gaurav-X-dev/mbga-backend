# Local Test Accounts

These accounts are for local development and isolated tests only. They are created by the backend seed script and use the local development OTP configured in the backend environment.

Do not use these values in staging or production.

## Seed Command

```powershell
cd backend
python scripts\seed_account_test_data.py
```

## Accounts

| Account type | Development mobile number | Login channel | Local OTP instruction | Expected landing page |
| --- | --- | --- | --- | --- |
| Super Admin | `+919999900001` | Admin | Use the local development OTP from backend settings. | Admin dashboard |
| Merchant | `+919999900002` | Merchant | Use the local development OTP from backend settings. | Merchant dashboard |
| Driver | `+919999900003` | Delivery | Use the local development OTP from backend settings. | Delivery API session context |
| Helper | `+919999900004` | Delivery | Use the local development OTP from backend settings. | Delivery API session context |

## Notes

- The seed script is idempotent.
- The numbers are reserved fake local-development identities.
- The frontend reads its backend base URL from `frontend/.env`.
- OTP values, token values, hashes, and backend secrets must not be written into frontend files.
