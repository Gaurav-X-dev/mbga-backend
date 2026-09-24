# Mobile Environment Checklist

Required values:

| Name | Purpose |
| --- | --- |
| `baseUrl` | API origin, for example `https://staging.example.com` |
| Customer onboarding access token | Registration profile/status/document upload |
| Customer onboarding refresh token | Refresh pending registration session |
| Customer full access token | Approved Customer APIs |
| Customer full refresh token | Existing Customer auth refresh |
| Merchant access token | Merchant Customer/KYC APIs |
| `customerId` | Merchant detail/approve/reject |
| `applicationId` | KYC detail |
| `fileId` | Document URL/content |

Backend deployment values to confirm before production:

| Setting | Requirement |
| --- | --- |
| `DOCUMENT_ENCRYPTION_SECRET` | Required outside local development |
| `DOCUMENT_STORAGE_PROVIDER` | Production provider still to be selected |
| `ALLOW_SKIPPED_KYC_SCAN_IN_LOCAL` | Local/test only; do not enable for staging/production |
| Malware scanner | Not connected yet; production approval requires `CLEAN` |
| Orphan cleanup | Schedule `python scripts/cleanup_orphaned_kyc_uploads.py --retention-hours 24 --execute` after dry-run review |


## SMS OTP delivery (backend-side)

The apps need no change for this: the OTP request, resend and verify contracts are unchanged.
What changes is only whether a real message is sent.

| Environment | `SMS_PROVIDER` | What the tester sees |
|---|---|---|
| Local / test | `mock` | No SMS. Sign in with `DEV_FIXED_OTP_CODE`. |
| Staging | `hanuotp` | A real SMS to a real handset. |
| Production | `hanuotp` | A real SMS to a real handset. |

`mock` is refused outside local/development/test, so a deployed environment cannot quietly stop
sending codes.

Before an app tester can receive a code from a deployed environment:

- [ ] `SMS_PROVIDER=hanuotp`
- [ ] `HANUOTP_BASE_URL`, `HANUOTP_API_KEY` and `HANUOTP_TEMPLATE_ID` set in the environment,
      never in the repository
- [ ] `HANUOTP_LIVE_SMOKE_TEST_ENABLED` unset or `false` (it is refused outside local anyway)
- [ ] DLT sender ID and OTP template registered with the vendor — without this the vendor accepts
      the request and delivers nothing
- [ ] One code received on a real handset

If a sign-in returns `503 OTP_DELIVERY_FAILED`, the backend reached the vendor and the vendor
refused or did not answer. The app should show its existing "could not send the code" message and
allow a retry; there is nothing for the app to change.

Full provider behaviour, retry policy and log-redaction rules: [otp-security.md](otp-security.md).
