# Mobile API Scope

## Customer App APIs

- POST `/api/v1/customer/auth/check-mobile`
- POST `/api/v1/customer/auth/otp/request`
- POST `/api/v1/customer/auth/otp/resend`
- POST `/api/v1/customer/auth/otp/verify`
- POST `/api/v1/customer/auth/token/refresh`
- POST `/api/v1/customer/auth/logout`
- POST `/api/v1/customer/auth/logout-all`
- GET `/api/v1/customer/auth/me`
- POST `/api/v1/customer/registration/otp/request`
- POST `/api/v1/customer/registration/otp/resend`
- POST `/api/v1/customer/registration/otp/verify`
- GET `/api/v1/customer/registration/fields`
- POST `/api/v1/customer/registration/profile`
- GET `/api/v1/customer/registration/status`

## Delivery App APIs

- POST `/api/v1/delivery/auth/otp/request`
- POST `/api/v1/delivery/auth/otp/resend`
- POST `/api/v1/delivery/auth/otp/verify`
- POST `/api/v1/delivery/auth/token/refresh`
- POST `/api/v1/delivery/auth/logout`
- POST `/api/v1/delivery/auth/logout-all`
- GET `/api/v1/delivery/auth/me`

## Merchant App APIs

- POST `/api/v1/merchant/auth/otp/request`
- POST `/api/v1/merchant/auth/otp/resend`
- POST `/api/v1/merchant/auth/otp/verify`
- POST `/api/v1/merchant/auth/token/refresh`
- POST `/api/v1/merchant/auth/logout`
- POST `/api/v1/merchant/auth/logout-all`
- GET `/api/v1/merchant/auth/me`

## Web-panel APIs

### Admin Web

- `/api/v1/admin/auth/*`
- `/api/v1/admin/dashboard/summary`
- `/api/v1/admin/users*`
- `/api/v1/admin/roles*`
- `/api/v1/admin/permissions*`
- `/api/v1/admin/audit-logs*`

### Merchant Web

- `/api/v1/merchant/auth/*`

Do not provide Admin roles, permissions, users, dashboard, or audit-log APIs to Customer or Delivery app developers.
