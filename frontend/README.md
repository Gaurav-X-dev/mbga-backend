# MBGA Web Panel

React + TypeScript web panel for **MBGA administrators** (Super Admin / Admin) and **merchants**.
It talks only to the existing FastAPI backend in `../backend`, which remains the source of truth for
authentication, permissions and business rules.

- API integration map and missing backend APIs: [docs/API_INTEGRATION.md](docs/API_INTEGRATION.md)

## Requirements

- Node.js 20+ (tested with Node 24) and npm
- The backend running on `http://127.0.0.1:8005` with the MBGA database migrated and seeded
- Redis is optional but strongly recommended: without it every permission-protected request waits
  several seconds for the permission cache to fail before falling back to the database

## Setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env   # only if .env does not exist yet
```

### Public environment variables

Vite loads `frontend/.env` (not `.env.example`). Everything in these variables is bundled into the
JavaScript sent to browsers, so **never** put database, JWT, OTP, SMS, encryption or any other secret here.

| Variable | Example | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8005/api/v1` | Backend API base URL (required for production builds) |
| `VITE_ENABLE_PREVIEW_MODE` | `false` | `true` shows local-development hints on the sign-in page. Keep `false` in production |

The backend must allow the panel's origin in `ALLOWED_CORS_ORIGINS` (it already allows
`http://127.0.0.1:5173` and `http://localhost:5173`).

## Start commands

Terminal 1 – backend:

```powershell
cd backend
venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8005 --reload
```

Terminal 2 – web panel:

```powershell
cd frontend
npm run dev          # http://127.0.0.1:5173
```

## Quality commands

```powershell
npm run typecheck    # TypeScript (strict), including e2e specs
npm run lint         # ESLint
npm run test         # Vitest unit, component and integration tests
npm run build        # Type check + production build into dist/
npm run test:e2e     # Playwright (needs the backend and seeded test data, see below)
```

## Production build

```powershell
$env:VITE_API_BASE_URL = "https://api.example.com/api/v1"   # or set it in .env.production
npm run build
```

Serve `dist/` as static files with a single-page-app fallback (every unknown path returns `index.html`).
The production build refuses to start without `VITE_API_BASE_URL`.

## Routes

| Route | Who | Required permission |
| --- | --- | --- |
| `/login` | Everyone | – |
| `/admin/dashboard` | Admin | `dashboard.view` |
| `/admin/merchants`, `/admin/merchants/:merchantId` | Admin | `merchants.view` |
| `/admin/merchants/new` | Admin | `merchants.create` |
| `/admin/customers` | Admin | – (not available in this backend release) |
| `/admin/users`, `/admin/users/:userId` | Admin | `users.view` |
| `/admin/roles`, `/admin/roles/:roleId` | Admin | `roles.view` |
| `/admin/permissions` | Admin | `permissions.view` |
| `/admin/audit-logs` | Admin | `audit_logs.view` |
| `/admin/profile` | Admin | – |
| `/merchant/dashboard` | Merchant | – |
| `/merchant/delivery-team`, `/merchant/delivery-team/:memberId` | Merchant | `delivery_users.view` |
| `/merchant/delivery-team/new` | Merchant | `delivery_users.create` |
| `/merchant/customers`, `/orders`, `/inventory`, `/payments`, `/reports` | Merchant | – (not available in this backend release) |
| `/merchant/profile` | Merchant | – |
| `/access-denied`, anything else | – | Access denied / not found pages |

## Authentication behaviour

- **Sign in** with a mobile number and a 4-digit verification code. The user picks *Admin panel* or
  *Merchant panel*; this selects the backend channel (`/admin/auth/*` or `/merchant/auth/*`).
  Choosing a panel never changes what a session is allowed to do – the backend issues tokens per channel.
- Mobile numbers are validated and normalised to `+91XXXXXXXXXX` exactly like the backend
  (`normalize_mobile_number`) **before** they are sent.
- The verification step has exactly four boxes with paste, arrow-key and backspace support, a masked
  number, "Change mobile number", an expiry countdown and a resend countdown (`resend_after`).
  Expired or used codes switch to "Request a new code".
- After verification the panel calls `GET /{channel}/auth/me` once, checks that `login_channel`
  matches the chosen panel, and caches the result (no repeated `/me` calls while navigating).
- **Session storage:** the backend returns bearer tokens in the response body (no HttpOnly cookie
  option), so the panel keeps `{channel, accessToken, refreshToken}` in `sessionStorage` under
  `mbga.web.session.v1`. The session survives a reload, is limited to the browser tab and is removed
  on sign-out. Tokens are never logged.
- **Refresh:** on a `401` the API client calls `POST /{channel}/auth/token/refresh` once (shared by all
  concurrent requests, because the backend rotates refresh tokens) and retries the request. If the
  refresh is rejected the session is cleared and the user is sent to sign in with
  "Your session has ended. Please sign in again." Network failures never sign the user out.
- **Sign out** calls `POST /{channel}/auth/logout` (best effort) and clears only the app's own session
  key and cached data. **Sign out from all devices** calls `POST /{channel}/auth/logout-all` after confirmation.
- After signing in, the user returns to the page they originally opened, but only if it belongs to the
  panel they signed in to (`safeRedirectPath`); otherwise they land on their dashboard.
- Local development: the backend's fixed development code (`DEV_FIXED_OTP_CODE`, currently `1234` in
  `backend/.env`) works only when `DEV_FIXED_OTP_ENABLED=true` in a local/dev/test environment.
  The code is not shown or stored anywhere in the web panel.

## Permission-based UI behaviour

- Navigation is built from the signed-in panel **and** the account's `effective_permissions`.
  Admin items never appear in the Merchant panel and vice versa.
- `ProtectedRoute` refuses a session from the other panel (`/admin/*` with a Merchant session shows
  "This area is not part of your panel" and makes no Admin API calls).
- `RequirePermission` shows an in-panel "You don’t have access to this page" message; `PermissionGuard`
  hides buttons and menu items the account cannot use.
- The backend still enforces every permission. A `403` from the server is shown as
  "You don’t have permission to perform this action."
- Modules without backend APIs are shown with a **Soon** tag and a page that says
  "This feature is not available in the current backend release." They never show data.

## Error handling

All HTTP errors are converted into one `AppError` shape (`src/api/errors.ts`):

```ts
class AppError { kind; status?; code?; userMessage; fieldErrors?; requestId?; debugMessage? }
```

Only `userMessage` is displayed. Backend codes (`OTP_INVALID`, `MERCHANT_CODE_EXISTS`, …), plain
`detail` strings and FastAPI validation lists are mapped to business language and, where possible,
to the matching form field. Server errors and tracebacks are never displayed.
Queries retry only network/timeout/server failures; validation, authentication and permission
failures are never retried.

## Project structure

```
src/
  api/          HTTP client, error normalisation, typed endpoint modules, query keys
  app/          providers, query client, router, route error page
  auth/         session storage, AuthProvider, route/permission guards, permission helpers
  components/   design system: common (Button, Icon, Menu, Tabs, badges), forms (Field, PhoneInput,
                OTPInput, Select…), feedback (states, Toast, Modal, ConfirmationDialog, Drawer),
                layout (AppShell, PageHeader, Breadcrumbs, Card, StatCard, DetailsPanel), tables
  config/       public env, navigation
  features/     login, dashboard, merchants, users, roles, permissions, audit-logs, profile,
                merchant-dashboard, delivery-team, system (not found / access denied / unavailable)
  hooks/        focus trap, countdown, debounced value, URL-backed list filters
  schemas/      shared Zod rules (mobile number, text lengths, optional email)
  styles/       design tokens and global styles
  test/         Vitest setup, render helpers, in-memory fake backend
  utils/        formatting, mobile number normalisation, business-language labels
e2e/            Playwright tests
```

## Tests

| Suite | Command | What it covers |
| --- | --- | --- |
| Unit | `npm run test` | mobile validation, error mapping, permission helpers, safe redirects, navigation filtering, merchant and delivery form schemas |
| Component | `npm run test` | four-digit OTP input, loading/empty/error states, confirmation dialog (focus trap, Escape, failures) |
| Integration | `npm run test` | full app with routes and guards against an in-memory fake of the backend contracts: OTP request/verify, `/me`, create merchant, merchant sign-in, create driver and helper, sign out, sign out everywhere, expired session and single refresh, permission denied, channel isolation, network failure |
| E2E (mocked) | `npm run test:e2e` | `e2e/login-otp.spec.ts` – four boxes, normalised number, dashboard |
| E2E (real backend) | `npm run test:e2e` | `e2e/core-flow.spec.ts`, `e2e/auth-and-access.spec.ts` |

### Local E2E test data

1. Use a local/development database only.
2. Seed the test accounts (idempotent, refuses to run outside local/development/test):

   ```powershell
   cd backend
   venv\Scripts\python scripts\seed_account_test_data.py
   ```

   This creates the Super Admin `+91 00000 00001` and the merchant manager `+91 00000 00002`.
3. Make sure `backend/.env` has `DEV_FIXED_OTP_ENABLED=true` and `DEV_FIXED_OTP_CODE=1234`.
4. Run `npm run test:e2e`. Overrides: `E2E_ADMIN_MOBILE`, `E2E_MERCHANT_MOBILE`, `E2E_OTP`.

Each run creates a new merchant, driver and helper with random `7XXXXXXXXX` mobile numbers and
`E2E-…` codes, so runs never collide. The backend has no delete endpoints, so these records remain in
the local database; they are clearly named `E2E …` and can be removed by resetting a disposable
database. `backend/scripts/cleanup_account_test_data.py` only removes the seeded `+91 00000 0000x` accounts.

**Rate limit:** the backend allows `OTP_MAX_REQUESTS_PER_HOUR` (5) verification-code requests per
number per hour. One full E2E run uses one request for the Admin number and one for the seeded merchant,
so the suite can run about five times per hour.
