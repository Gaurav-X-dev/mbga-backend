# Authentication API Comparison

| Operation | Admin | Merchant | Customer | Delivery | Shared implementation? | Difference justified? |
| --- | --- | --- | --- | --- | --- | --- |
| check-mobile | n/a | n/a | /customer/auth/check-mobile only | n/a | no | yes; route fixes channel/purpose and account policy differs |
| otp/request | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| otp/resend | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| otp/verify | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| token/refresh | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| logout | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| logout-all | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |
| me | channel route | channel route | channel route | channel route | yes via build_channel_auth_router + AuthenticationService | yes; route fixes channel/purpose and account policy differs |

## Contract Notes

- OTP verification accepts `otp` as a string matching `^[0-9]{4}$`.
- Channel-specific routes set channel server-side; clients should not be trusted to choose channel by body.
- Legacy `/api/v1/auth/*` routes are absent; use channel-specific auth URLs only.
- Customer registration uses `CUSTOMER_REGISTRATION` purpose and returns onboarding-scope access.
- Full customer login is denied until the customer profile/documents are approved.
