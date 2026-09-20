# MBGA Web Panel – API integration map and API gaps

Source of truth: `backend/docs/openapi-admin.json`, `backend/docs/openapi-merchant.json`, the live
`/openapi/{channel}.json`, and the routers under `backend/app/modules/*/router.py` (reviewed 2026-09-16,
Alembic head `20260916_0007`). Only routes that exist are called. Base URL: `VITE_API_BASE_URL`
(`http://127.0.0.1:8005/api/v1`).

## Error formats handled

| Backend shape | Example | Panel behaviour |
| --- | --- | --- |
| `{"detail": {"code", "message"}}` | `OTP_INVALID`, `MERCHANT_CODE_EXISTS` | Mapped by code to a safe message, and to a form field where relevant |
| `{"detail": "text"}` | `Permission denied`, `Authentication required`, `User not found` | Mapped by pattern, otherwise a message based on the status |
| `{"detail": [ {type, loc, msg} ]}` (422) | missing / too short / pattern / value error | Field messages in plain language |
| 5xx / plain text / traceback | invalid mobile number on `otp/request` | "The service is temporarily unavailable. Please try again." |
| No response | network, CORS, timeout | "We could not connect to the server…" |

## Screen-to-API map

### Authentication (both panels; `{channel}` is `admin` or `merchant`)

| UI action | Method and path | Request | Response used |
| --- | --- | --- | --- |
| Send verification code | `POST /{channel}/auth/otp/request` | `mobile_number` (`+91XXXXXXXXXX`), `country_code`, `device` | `request_id`, `expires_in`, `resend_after` |
| Resend code | `POST /{channel}/auth/otp/resend` (falls back to `otp/request` if the old code is used/expired) | `request_id`, `device` | same as above |
| Verify and continue | `POST /{channel}/auth/otp/verify` | `request_id`, `otp` (4 digits), `device` | `token.access_token`, `token.refresh_token` |
| Load account | `GET /{channel}/auth/me` | Bearer | `display_name`, `mobile_number`, `active_roles`, `effective_permissions`, `login_channel`, `status` |
| Renew session | `POST /{channel}/auth/token/refresh` | `refresh_token`, `device_id` | new token pair (old one is revoked) |
| Sign out | `POST /{channel}/auth/logout` | `refresh_token`, `device_id` | 204 |
| Sign out from all devices | `POST /{channel}/auth/logout-all` | Bearer | 204 |

### Admin panel

| Screen | Calls |
| --- | --- |
| Dashboard | `GET /admin/dashboard/summary`; `GET /admin/merchants?limit=1` (+ `status=ACTIVE`, `status=BLOCKED`) for counts from `total`; `GET /admin/audit-logs?page_size=6` |
| Merchants list | `GET /admin/merchants?search&status&city&state&limit&offset`; row actions `POST /admin/merchants/{id}/block`, `/unblock`, `/activate` |
| Add merchant | `POST /admin/merchants` (`merchant_code`, `business_name`, `contact_person_name`, `mobile_number`, `email`, `gst_number`, `address_line_1/2`, `city`, `state`, `postal_code`) |
| Merchant detail / edit | `GET /admin/merchants/{id}`; `PATCH /admin/merchants/{id}` (changed fields only); block/unblock |
| Merchant staff tab | `GET /admin/merchants/{id}/users`; `POST /admin/merchants/{id}/users`; `PATCH /admin/merchants/{id}/users/{user_id}` (name, email, status) |
| Users list | `GET /admin/users?search&status&limit&offset`; `POST /admin/users/{id}/activate`, `/block`, `/unblock`, `/logout-all` |
| Add user | `GET /admin/users?search=<mobile>` (duplicate check) then `POST /admin/users` |
| User detail | `GET /admin/users/{id}`; `PATCH /admin/users/{id}` (name, email); `GET/POST /admin/users/{id}/roles`; `DELETE /admin/users/{id}/roles/{assignment_id}`; `GET /admin/users/{id}/allowed-channels`; `GET /admin/users/{id}/effective-permissions?login_channel=`; `GET /admin/roles?is_active=true` (role names); `GET /admin/permissions/grouped` (permission names) |
| Roles list | `GET /admin/roles?search&is_active&login_channel&page&page_size`; `POST /admin/roles` |
| Role detail | `GET /admin/roles/{id}`; `PATCH /admin/roles/{id}`; `POST /admin/roles/{id}/activate`, `/deactivate`; `DELETE /admin/roles/{id}`; `GET/PUT /admin/roles/{id}/permissions`; `GET/PUT /admin/roles/{id}/channels`; `GET /admin/roles/{id}/users`; `GET /admin/permissions/grouped` |
| Permissions | `GET /admin/permissions/grouped?is_active=true` |
| Audit logs | `GET /admin/audit-logs?date_from&date_to&action&entity_type&actor_user_id&page&page_size`; `GET /admin/audit-logs/{id}`; `GET /admin/users?limit=100` (names for "Performed by") |
| My account | `/admin/auth/me`, `logout`, `logout-all` |

### Merchant panel

| Screen | Calls |
| --- | --- |
| Dashboard | `GET /merchant/delivery-users?limit=1` (+ `delivery_user_type=DRIVER|HELPER&status=ACTIVE`, `status=BLOCKED`) for counts; `GET /merchant/delivery-users?limit=5` for recent members |
| Delivery team list | `GET /merchant/delivery-users?search&delivery_user_type&status&limit&offset`; `POST /merchant/delivery-users/{id}/block`, `/unblock`, `/activate` |
| Add team member | `POST /merchant/delivery-users` (`delivery_user_type`, `full_name`, `mobile_number`, `email`, `employee_code`, `driving_license_number`, `driving_license_expiry` (yyyy-mm-dd), `address`) |
| Team member detail / edit | `GET /merchant/delivery-users/{id}`; `PATCH /merchant/delivery-users/{id}` (changed fields only) |
| My account | `/merchant/auth/me`, `logout`, `logout-all` |

Merchant screens never call `/admin/*`. The backend scopes every `/merchant/delivery-users` call to
the signed-in merchant.

## Screen completion

| Screen | Role | Real API | Loading | Empty | Error | Responsive | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sign in (mobile + 4-digit code) | Both | Yes | Yes | – | Yes | Yes | Unit, integration, E2E |
| Admin dashboard | Admin | Yes | Yes | Yes | Yes | Yes | Integration, E2E (mocked) |
| Merchants list | Admin | Yes | Yes | Yes | Yes | Yes (cards on phones) | Integration, E2E |
| Add merchant (form → review → done) | Admin | Yes | Yes | – | Yes | Yes | Unit, integration, E2E |
| Merchant detail / edit / staff | Admin | Yes | Yes | Yes | Yes | Yes | E2E (detail, staff tab) |
| Customers | Admin | **No API** | – | Placeholder | – | Yes | Manual |
| Users list / add | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data) |
| User detail (roles, access) | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data) |
| Roles list / add | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data) |
| Role detail (permissions, panels, people) | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data) |
| Permissions catalogue | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data) |
| Audit logs + details drawer | Admin | Yes | Yes | Yes | Yes | Yes | Manual (real data, date filters checked) |
| My account | Both | Yes | – | – | Yes | Yes | Integration (sign-out actions from the account menu) |
| Merchant dashboard | Merchant | Yes | Yes | Yes | Yes | Yes | Integration, E2E |
| Delivery team list | Merchant | Yes | Yes | Yes | Yes | Yes | Integration, E2E |
| Add team member | Merchant | Yes | Yes | – | Yes | Yes | Unit, integration, E2E |
| Team member detail / edit | Merchant | Yes | Yes | – | Yes | Yes | Integration, E2E |
| Customers, orders, inventory, payments, reports | Merchant | **No API** | – | Placeholder | – | Yes | E2E (orders placeholder) |
| Not found / access denied / service unavailable | Both | – | – | – | Yes | Yes | Integration, E2E |

"Manual (real data)" means the screen was checked in a real browser against the local backend
(desktop, tablet and phone widths) but has no automated test yet.

## API gaps and backend observations

| Required UI capability | Missing API or field | Affected role | Recommended backend contract |
| --- | --- | --- | --- |
| Customer review (pending/approved/rejected lists, details, documents, approve, reject with reason, timeline) | No `/admin/customers*` routes (customer module only has customer-app registration routes) | Admin | `GET /admin/customers?status&search&page`, `GET /admin/customers/{id}`, `GET /admin/customers/{id}/documents` (short-lived signed download URLs), `POST /admin/customers/{id}/approve`, `POST /admin/customers/{id}/reject` `{reason}` (required), `GET /admin/customers/{id}/timeline`; permissions `customers.view/approve/reject`, `customer_documents.view` |
| Merchant customers | No `/merchant/customers*` | Merchant | Merchant-scoped list/detail with the same filters |
| Orders | No orders API | Merchant | `GET/POST /merchant/orders`, `GET/PATCH /merchant/orders/{id}`, assign/cancel actions; `orders.*` permissions already seeded |
| Inventory | No inventory API | Merchant | `GET /merchant/inventory`, `POST /merchant/inventory/adjustments` |
| Payments | No payments API | Merchant | `GET /merchant/payments`, `POST /merchant/payments` |
| Reports | No reports API | Merchant | `GET /merchant/reports/{report}?from&to` (+ export) |
| Merchant dashboard summary | No summary endpoint; counts are derived from list totals (4 requests) | Merchant | `GET /merchant/dashboard/summary` returning team counts and, later, orders needing attention |
| Admin dashboard merchant and pending-approval counts | `dashboard/summary` has no merchant or customer counts (merchant counts come from 3 list requests) | Admin | Add `merchants`, `active_merchants`, `blocked_merchants`, `pending_customer_approvals` |
| Business name in the Merchant panel header | `/merchant/auth/me` always returns `merchant: null` | Merchant | Populate `merchant: {id, business_name, merchant_code}` |
| Filter users by role | `GET /admin/users` has no `role` filter; search does not include `full_name` | Admin | Add `role_id` filter and full-name search |
| Sort columns | No `sort` parameter on any list | Admin, Merchant | `sort=field` / `sort=-field` |
| Audit log search and outcome | No free-text search or outcome field; actor names are not returned | Admin | `search` parameter, `outcome` field, `actor_name` in responses |
| Role user count in the list | Only per-role `GET /roles/{id}/users` | Admin | `user_count` on `RoleResponse` |
| Merchant user update response | `PATCH /admin/merchants/{id}` returns `primary_user_id: null` | Admin | Return the same value as `GET` |
| Invalid mobile number on sign-in | `POST /{channel}/auth/otp/request` raises an unhandled `ValueError` (HTTP 500 with a traceback when `DEBUG=true`) instead of 422 | Both | Catch it and return `422 {"code": "INVALID_MOBILE_NUMBER"}` (the panel validates first, so users are not affected) |
| Duplicate merchant email | `merchants.email` is unique but not pre-checked, so a duplicate gives a database error (500) | Admin | Return `409 {"code": "MERCHANT_EMAIL_EXISTS"}` (the panel currently shows a hint about the email) |
| Duplicate user mobile number | `POST /admin/users` does not check `mobile_number` (column is not unique) | Admin | Return `409 {"code": "MOBILE_ALREADY_EXISTS"}` (the panel checks via search before creating) |
| Editing a user's mobile number | `PATCH /admin/users/{id}` stores `mobile_number` without normalisation | Admin | Normalise and check uniqueness; until then the panel does not allow editing it |
| Deleting a role that has users | No check before delete (likely a database error) | Admin | Return `409` with a clear code; the panel disables delete while the role has people |
| Immediate sign-out after block | `POST /admin/users/{id}/block` does not revoke sessions; access tokens are not checked against revoked sessions, so they stay valid for up to 15 minutes | Admin | Revoke sessions on block and check the session in `require_authenticated_user` |
| Audit actor for user/role changes | `users` and `roles` routers write `actor_user_id = None` | Admin | Record the acting user |
| Request correlation | No `X-Request-ID` header | Both | Return a request ID so support can trace issues (the panel already keeps it if present) |
| Performance | Redis is not running locally; every permission check waits ~2 s per Redis call before falling back (≈4.5 s per protected request) | Both | Run Redis locally, or add a short connect timeout / circuit breaker in `PermissionCache` |
| Token signing key length | The local `JWT_SIGNING_SECRET` is 20 bytes (PyJWT warns below 32) | Both | Use a 32+ byte secret outside local development |
