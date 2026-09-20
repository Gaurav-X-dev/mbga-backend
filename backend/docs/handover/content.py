"""Content of the Customer and Merchant authentication handover.

Single source for both the Markdown and the DOCX output (see build_handover.py).
Block types:
  ("h1"|"h2"|"h3", text)          numbered headings are written into the text
  ("p", text)                      paragraph; **bold** and `code` spans are supported
  ("bullets", [text, ...])
  ("numbers", [text, ...])
  ("code", text)
  ("callout", kind, text)          kind: info | warning | critical
  ("table", headers, rows, widths_cm, options)   options: {"landscape": bool, "font": pt}
  ("pagebreak",)
"""

TITLE = "MBGA Customer and Merchant Authentication API Implementation Handover"
META = [
    ("Project", "MBGA Commercial LPG Platform"),
    ("Audience", "Customer App and Merchant App developers"),
    ("Prepared by", "Backend Team"),
    ("Document date", "17 September 2026"),
    ("Backend framework", "FastAPI (Python), Pydantic v2, SQLAlchemy 2 async, MariaDB"),
    ("API version", "/api/v1 (backend application version 0.1.0)"),
    ("Database migration head", "20260917_0010"),
    ("Document status", "Ready for Integration with Documented Limitations"),
]

LEGEND = [
    ("Implemented and tested", "Exists in the backend and is covered by automated or live tests."),
    ("Implemented with limitations", "Works, but a documented dependency prevents real-world use."),
    ("Proposed by frontend, not available", "Appears only in the frontend API specification."),
    ("Pending backend development", "Planned work that has not been built."),
    ("Blocked by business decision", "Needs a Product Owner decision before it can be built or enabled."),
    ("Blocked by external configuration", "Needs a vendor, credential or infrastructure setting."),
    ("TO BE CONFIRMED FROM OPENAPI OR BACKEND CODE", "Could not be verified from the supplied sources."),
]

B = []  # blocks


def h1(t): B.append(("h1", t))
def h2(t): B.append(("h2", t))
def h3(t): B.append(("h3", t))
def p(t): B.append(("p", t))
def bullets(*items): B.append(("bullets", list(items)))
def numbers(*items): B.append(("numbers", list(items)))
def code(t): B.append(("code", t.strip("\n")))
def callout(kind, t): B.append(("callout", kind, t))
def table(headers, rows, widths, **options): B.append(("table", headers, rows, widths, options))
def pagebreak(): B.append(("pagebreak",))


# ---------------------------------------------------------------------------------------------
h1("1. Executive summary")
p("The backend authentication for the Customer and Merchant apps has been rebuilt and tested. "
  "Sign-in is **OTP-only** (no passwords). Each app has its own route prefix, every signed-in request "
  "is checked against a live server-side session, and responses now tell the app which screen to open "
  "(`next_action`).")
table(["Question", "Answer"], [
    ["Can the Customer App team start integration?", "**Yes.** Registration (onboarding), profile, submit-for-review, status, full sign-in, refresh and logout are available."],
    ["Can the Merchant App team start integration?", "**Yes.** Sign-in, session restore, refresh, logout and logout-all are available. Customer review endpoints exist but need role permissions before use."],
    ["Is anything production-ready?", "**No.** Sign-in cannot be completed outside local development until a real SMS vendor is integrated."],
], [5.2, 12.0])
callout("warning",
        "Three limitations apply to every environment beyond local development:\n"
        "1. Real SMS delivery is not implemented. Outside local development, code requests return "
        "503 OTP_DELIVERY_FAILED until an SMS vendor is integrated.\n"
        "2. Customer KYC document upload (Aadhaar/PAN, FSSAI/GST) is not implemented.\n"
        "3. The Customer review permissions (customers.view, customers.approve, customers.reject) are "
        "not assigned to any Merchant role yet.")
p("**Integrate now:** the channel-specific sign-in routes, secure storage of the access and refresh "
  "tokens, single-flight refresh, `next_action` navigation, the standard error envelope and the "
  "Customer registration draft and submit flow.")
p("**Do not treat as production-ready:** real OTP delivery, real Customer approval (no documents can be "
  "uploaded and no role can review yet), and any feature outside authentication.")

h2("1.1 Status labels used in this document")
table(["Label", "Meaning"], [[a, b] for a, b in LEGEND], [6.0, 11.2])

# ---------------------------------------------------------------------------------------------
h1("2. Scope")
table(["In scope", "Out of scope"], [
    ["OTP request, resend and verification", "Orders, pricing, payments, invoices"],
    ["Access and refresh tokens, token refresh", "Inventory, delivery and dispatch, reports, expenses, notifications"],
    ["Session restoration and the current-user endpoint", "Customer KYC document upload (pending backend work)"],
    ["Customer onboarding, profile, submission and status", "Production SMS vendor dispatch (pending vendor)"],
    ["Merchant review: list, approve and reject Customer registrations", "Password login and password recovery (not part of the system)"],
    ["Logout and logout from all devices", "Staff-created customers (frontend `POST /customers`), not available"],
    ["Device and push-token handling", "Delivery App (mentioned only where the shared implementation matters)"],
    ["Authentication errors, navigation and security controls", "Admin web panel"],
], [8.6, 8.6])
p("Sources used: the current backend code, `docs/openapi-customer.json`, `docs/openapi-merchant.json`, "
  "the matching Postman collections, `docs/mobile-auth-integration.md`, the backend implementation report "
  "of 17 September 2026 and the frontend `API_SPEC.md` (Backend API Specification).")

# ---------------------------------------------------------------------------------------------
h1("3. Current readiness summary")
table(["Area", "Customer App", "Merchant App", "Status", "Notes"], [
    ["OTP request and resend", "Ready with limitation", "Ready with limitation", "Ready with limitation", "Works locally with the development code; no real SMS."],
    ["OTP verification", "Ready", "Ready", "Ready", "Returns tokens and navigation fields."],
    ["Access and refresh tokens", "Ready", "Ready", "Ready", "15-minute access token, rotating refresh token."],
    ["Current-user session", "Ready", "Ready", "Ready", "Channel-specific `/auth/me`."],
    ["Logout", "Ready", "Ready", "Ready", "Ends the server session immediately."],
    ["Logout all devices", "Ready", "Ready", "Ready", "Ends every session of the user."],
    ["Customer onboarding", "Ready with limitation", "Not applicable", "Ready with limitation", "Profile has 4 fields only; no address or documents."],
    ["Registration submission", "Ready with limitation", "Not applicable", "Ready with limitation", "Submits without documents (upload pending)."],
    ["Customer approval", "Not applicable", "Blocked", "Blocked", "Endpoints exist; no role holds the permissions."],
    ["Real SMS delivery", "Blocked", "Blocked", "Blocked", "Vendor not selected or integrated."],
    ["KYC document upload", "Pending", "Not applicable", "Pending", "No upload API or file storage."],
    ["Production readiness", "Blocked", "Blocked", "Blocked", "SMS, document upload, permissions, proxy settings."],
], [3.6, 2.9, 2.9, 2.9, 4.9], font=8)

# ---------------------------------------------------------------------------------------------
h1("4. Implemented backend capabilities")
table(["Capability", "What it means for the mobile apps", "Label"], [
    ["Session-aware access-token validation", "Every Bearer request is checked against a live session and the account state. A valid signature alone is not enough.", "Implemented and tested"],
    ["Immediate session revocation", "After logout, logout-all, refresh, admin sign-out or a block, the old access token fails on the next request.", "Implemented and tested"],
    ["Onboarding-token isolation", "Registration tokens work only on `/customer/registration/*`. Elsewhere they return 401 TOKEN_TYPE_NOT_ALLOWED.", "Implemented and tested"],
    ["Authenticated Customer registration", "Profile, submit and status need the onboarding token. The mobile number is taken from the session.", "Implemented and tested"],
    ["Onboarding refresh", "The registration session can be refreshed and stays restricted.", "Implemented and tested"],
    ["Registration submission", "`POST /customer/registration/submit` moves a complete draft to UNDER_REVIEW.", "Implemented with limitations (no documents)"],
    ["Merchant-scoped approval and rejection", "Reviewers see and decide only applications for their own merchant.", "Implemented with limitations (no role has the permissions)"],
    ["Mobile navigation fields", "Verify and `/me` return role, user_type, session_type, statuses and `next_action`.", "Implemented and tested"],
    ["Standard error contract", "Sign-in and registration errors use `{\"detail\": {code, message, fields, request_id}}`.", "Implemented and tested"],
    ["Refresh rotation and reuse detection", "Each refresh token works once. Replaying an old one ends the whole sign-in chain.", "Implemented and tested"],
    ["OTP abuse protection", "Limits per number, device and IP, plus an hourly wrong-code lockout. 429 responses include Retry-After.", "Implemented and tested"],
    ["Authentication audit events", "Sign-in events are recorded with a masked number and hashed device ID; no codes or tokens.", "Implemented and tested"],
    ["Security headers and no-store", "Auth responses are never cached; standard security headers are set.", "Implemented and tested"],
    ["Environment startup guards", "Outside local environments the server refuses weak secrets, debug mode, the mock SMS provider and the fixed development code.", "Implemented and tested"],
    ["Device and FCM-token storage", "Device details and the push token are stored per session and cleared on logout.", "Implemented and tested"],
    ["Configurable OTP length", "The code length follows the backend setting (currently 4 digits).", "Implemented and tested"],
    ["Unused authentication code removed", "Legacy placeholder routes and services were deleted; no route changes for the apps.", "Implemented"],
], [4.4, 9.0, 3.8], font=8)

# ---------------------------------------------------------------------------------------------
h1("5. Token types")
table(["Token", "Issued by", "Accepted by", "Lifetime"], [
    ["Merchant access token", "Merchant verify and refresh (M-03, M-04)", "Merchant `/auth/*` routes and Merchant business APIs", "15 minutes"],
    ["Full Customer access token", "Customer verify and refresh (C-04, C-05)", "Customer `/auth/*` routes and future Customer business APIs", "15 minutes"],
    ["Onboarding access token", "Registration verify and refresh (R-03, R-04)", "`/api/v1/customer/registration/*` only", "15 minutes"],
    ["Refresh token", "Every verify and refresh response", "The `token/refresh` and `logout` routes of the prefix that issued it; single use", "30 days"],
], [3.8, 5.0, 5.6, 2.8])
p("API IDs refer to the inventory in section 8. The `session_type` field in verify and `/me` responses is `access` for Merchant and full Customer "
  "sessions and `onboarding` for registration sessions. Tokens are rejected by other apps "
  "(TOKEN_CHANNEL_MISMATCH) and by routes that need the other session type (TOKEN_TYPE_NOT_ALLOWED).")
callout("critical", "Never send an onboarding token to full Customer APIs, and never send a full Customer token "
        "to `/customer/registration/*`. Both return 401 TOKEN_TYPE_NOT_ALLOWED.")

# ---------------------------------------------------------------------------------------------
h1("6. Merchant App authentication flow")
table(["Step", "Method and path", "Auth", "Send", "Read from response", "Mobile action"], [
    ["1. Request OTP", "POST /api/v1/merchant/auth/otp/request", "None", "mobile_number, device", "request_id, expires_in, resend_after", "Show code screen and timers. Errors: 422, 429 (Retry-After), 503."],
    ["2. Resend timer", "(client)", "-", "-", "resend_after", "Enable Resend when the timer ends."],
    ["3. Resend OTP", "POST /api/v1/merchant/auth/otp/resend", "None", "request_id, device", "new request_id", "Replace the stored request_id. Errors: 400, 429."],
    ["4. Verify OTP", "POST /api/v1/merchant/auth/otp/verify", "None", "request_id, otp, device (with fcm_token)", "token, role, next_action, merchant", "Errors: 400 OTP_*, 403 account codes, 429."],
    ["5. Store tokens", "(client)", "-", "-", "access_token, refresh_token", "Keychain / Keystore, both tokens together."],
    ["6. Route", "(client)", "-", "-", "next_action", "OPEN_MERCHANT_HOME. Denied states arrive as 403 codes, not as next_action."],
    ["7. Restore session", "GET /api/v1/merchant/auth/me", "Bearer (access)", "-", "role, effective_permissions, merchant, next_action", "Run on app start after a refresh. 401 means sign in; 403 means show the account screen."],
    ["8. Refresh", "POST /api/v1/merchant/auth/token/refresh", "Refresh token in body", "refresh_token, device (optional)", "new access_token, refresh_token", "Single-flight; store both. Errors: 401, 403."],
    ["9. Logout", "POST /api/v1/merchant/auth/logout", "Refresh token in body", "refresh_token", "204", "Clear tokens even if the call fails."],
    ["10. Logout all", "POST /api/v1/merchant/auth/logout-all", "Bearer (access)", "-", "204", "Clear tokens; other devices are signed out."],
], [2.4, 5.4, 2.6, 3.8, 4.6, 6.8], landscape=True, font=8)

# ---------------------------------------------------------------------------------------------
h1("7. Customer App registration and login flows")
h2("7.1 First-time registration (onboarding session)")
table(["Step", "Method and path", "Auth", "Send", "Read from response", "Mobile action"], [
    ["1. Determine state", "POST /api/v1/customer/auth/check-mobile", "None", "mobile_number", "registered, registration_allowed", "false: start registration. true: try sign-in (7.2); offer \"Continue registration\" if no code arrives. 429 has Retry-After."],
    ["2. Request code", "POST /api/v1/customer/registration/otp/request", "None", "mobile_number, device", "request_id, expires_in, resend_after", "Show code screen."],
    ["2a. Resend", "POST /api/v1/customer/registration/otp/resend", "None", "request_id", "new request_id", "Replace request_id."],
    ["3. Verify", "POST /api/v1/customer/registration/otp/verify", "None", "request_id, otp, device", "token, session_type=onboarding, is_new_user, next_action", "Store the onboarding pair securely, separately from full tokens."],
    ["4. Context", "GET /api/v1/customer/registration/me", "Bearer (onboarding)", "-", "account_status, approval_status, profile_completion_status, customer_profile, next_action", "Navigate by next_action."],
    ["5. Form fields", "GET /api/v1/customer/registration/fields", "None", "-", "fields[] (api_field_name, required, allowed_values, required_for)", "Build or validate the form."],
    ["6. Create draft", "POST /api/v1/customer/registration/profile", "Bearer (onboarding)", "merchant_code, customer_type, name, gst_number", "profile (status PROFILE_INCOMPLETE)", "409: load with GET /registration/profile. Update with PATCH."],
    ["7. Submit", "POST /api/v1/customer/registration/submit", "Bearer (onboarding)", "-", "status UNDER_REVIEW, next_action WAIT_FOR_APPROVAL", "422 REGISTRATION_INCOMPLETE lists missing fields."],
    ["8. Status", "GET /api/v1/customer/registration/status", "Bearer (onboarding)", "-", "status, next_action, rejection_reason", "Poll on app open, not in a tight loop."],
    ["9. Refresh", "POST /api/v1/customer/registration/token/refresh", "Refresh token in body", "refresh_token", "new onboarding pair", "Stays an onboarding session."],
    ["10. Approved", "GET /api/v1/customer/registration/status", "Bearer (onboarding)", "-", "status APPROVED, next_action SIGN_IN", "Call /customer/registration/logout, then run 7.2."],
], [2.2, 5.6, 2.6, 3.6, 5.0, 6.6], landscape=True, font=8)
callout("warning", "Real Customer approval must not be enabled yet: documents cannot be uploaded and no Merchant role "
        "holds the review permissions. The flow above can be tested end to end only in a local or test "
        "environment where a test role is given those permissions.")
h2("7.2 Existing approved Customer sign-in (full session)")
table(["Step", "Method and path", "Auth", "Send", "Read from response", "Mobile action"], [
    ["1. Request code", "POST /api/v1/customer/auth/otp/request", "None", "mobile_number, device", "request_id, expires_in, resend_after", "Numbers that are not approved customers also get 202 but no SMS."],
    ["2. Resend", "POST /api/v1/customer/auth/otp/resend", "None", "request_id", "new request_id", "Replace request_id."],
    ["3. Verify", "POST /api/v1/customer/auth/otp/verify", "None", "request_id, otp, device", "token, session_type=access, role=customer, next_action, customer_profile", "OTP_INVALID may also mean the number is not an approved customer."],
    ["4. Route", "(client)", "-", "-", "next_action", "OPEN_CUSTOMER_HOME, or an account screen."],
    ["5. Restore", "GET /api/v1/customer/auth/me", "Bearer (access)", "-", "account_status, customer_profile, next_action", "On app start after a refresh."],
    ["6. Refresh", "POST /api/v1/customer/auth/token/refresh", "Refresh token in body", "refresh_token, device", "new pair", "Single-flight."],
    ["7. Logout", "POST /api/v1/customer/auth/logout", "Refresh token in body", "refresh_token", "204", "Clear tokens."],
    ["8. Logout all", "POST /api/v1/customer/auth/logout-all", "Bearer (access)", "-", "204", "Clear tokens."],
], [2.2, 5.6, 2.6, 3.6, 5.0, 6.6], landscape=True, font=8)

# ---------------------------------------------------------------------------------------------
h1("8. Actual API inventory")
p("All paths below were verified in the backend routers and the generated OpenAPI files. "
  "Base URL: `<environment host>/api/v1`.")
h2("8.1 Merchant authentication")
INV_COLS = ["API ID", "Method", "Actual backend path", "Purpose", "Auth", "Token type", "Status"]
INV_W = [1.4, 1.4, 8.6, 4.6, 1.6, 2.4, 5.9]
table(INV_COLS, [
    ["M-01", "POST", "/api/v1/merchant/auth/otp/request", "Request a code", "No", "-", "Implemented with limitations (SMS)"],
    ["M-02", "POST", "/api/v1/merchant/auth/otp/resend", "Replace a code", "No", "-", "Implemented with limitations (SMS)"],
    ["M-03", "POST", "/api/v1/merchant/auth/otp/verify", "Verify code, issue tokens", "No", "-", "Implemented and tested"],
    ["M-04", "POST", "/api/v1/merchant/auth/token/refresh", "Rotate token pair", "Body", "Refresh", "Implemented and tested"],
    ["M-05", "GET", "/api/v1/merchant/auth/me", "Current user", "Yes", "Access", "Implemented and tested"],
    ["M-06", "POST", "/api/v1/merchant/auth/logout", "End this session", "Body", "Refresh", "Implemented and tested"],
    ["M-07", "POST", "/api/v1/merchant/auth/logout-all", "End all sessions", "Yes", "Access", "Implemented and tested"],
], INV_W, landscape=True, font=8)
h2("8.2 Customer authentication (full session)")
table(INV_COLS, [
    ["C-01", "POST", "/api/v1/customer/auth/check-mobile", "Registration exists?", "No", "-", "Implemented and tested"],
    ["C-02", "POST", "/api/v1/customer/auth/otp/request", "Request a code", "No", "-", "Implemented with limitations (SMS)"],
    ["C-03", "POST", "/api/v1/customer/auth/otp/resend", "Replace a code", "No", "-", "Implemented with limitations (SMS)"],
    ["C-04", "POST", "/api/v1/customer/auth/otp/verify", "Verify code, issue tokens", "No", "-", "Implemented and tested"],
    ["C-05", "POST", "/api/v1/customer/auth/token/refresh", "Rotate token pair", "Body", "Refresh", "Implemented and tested"],
    ["C-06", "GET", "/api/v1/customer/auth/me", "Current user", "Yes", "Full access", "Implemented and tested"],
    ["C-07", "POST", "/api/v1/customer/auth/logout", "End this session", "Body", "Refresh", "Implemented and tested"],
    ["C-08", "POST", "/api/v1/customer/auth/logout-all", "End all sessions", "Yes", "Full access", "Implemented and tested"],
], INV_W, landscape=True, font=8)
h2("8.3 Customer registration (onboarding session)")
table(INV_COLS, [
    ["R-01", "POST", "/api/v1/customer/registration/otp/request", "Request a code", "No", "-", "Implemented with limitations (SMS)"],
    ["R-02", "POST", "/api/v1/customer/registration/otp/resend", "Replace a code", "No", "-", "Implemented with limitations (SMS)"],
    ["R-03", "POST", "/api/v1/customer/registration/otp/verify", "Verify, issue onboarding tokens", "No", "-", "Implemented and tested"],
    ["R-04", "POST", "/api/v1/customer/registration/token/refresh", "Rotate onboarding pair", "Body", "Refresh", "Implemented and tested"],
    ["R-05", "GET", "/api/v1/customer/registration/me", "Onboarding context", "Yes", "Onboarding", "Implemented and tested"],
    ["R-06", "POST", "/api/v1/customer/registration/logout", "End onboarding session", "Body", "Refresh", "Implemented and tested"],
    ["R-07", "POST", "/api/v1/customer/registration/logout-all", "End all sessions", "Yes", "Onboarding", "Implemented and tested"],
    ["R-08", "GET", "/api/v1/customer/registration/fields", "Form definition", "No", "-", "Implemented"],
    ["R-09", "POST", "/api/v1/customer/registration/profile", "Create draft", "Yes", "Onboarding", "Implemented with limitations (4 fields)"],
    ["R-10", "GET", "/api/v1/customer/registration/profile", "Read draft", "Yes", "Onboarding", "Implemented and tested"],
    ["R-11", "PATCH", "/api/v1/customer/registration/profile", "Update draft", "Yes", "Onboarding", "Implemented and tested"],
    ["R-12", "POST", "/api/v1/customer/registration/submit", "Submit for review", "Yes", "Onboarding", "Implemented with limitations (no documents)"],
    ["R-13", "GET", "/api/v1/customer/registration/status", "Review status", "Yes", "Onboarding", "Implemented and tested"],
], INV_W, landscape=True, font=8)
h2("8.4 Customer review used by the Merchant App")
table(INV_COLS, [
    ["MR-01", "GET", "/api/v1/merchant/customers?status=UNDER_REVIEW", "List applications (customers.view)", "Yes", "Merchant access", "Blocked by business decision (permissions)"],
    ["MR-02", "POST", "/api/v1/merchant/customers/{customer_id}/approve", "Approve (customers.approve)", "Yes", "Merchant access", "Blocked by business decision (permissions)"],
    ["MR-03", "POST", "/api/v1/merchant/customers/{customer_id}/reject", "Reject (customers.reject)", "Yes", "Merchant access", "Blocked by business decision (permissions)"],
], INV_W, landscape=True, font=8)
p("No other authentication routes exist. There is no generic `/api/v1/auth/*` route: the old placeholder "
  "routes return 404.")

# ---------------------------------------------------------------------------------------------
h1("9. Frontend-to-backend contract mapping")
p("The frontend specification proposes generic paths and camelCase fields. The backend uses channel-specific "
  "paths and snake_case fields. **Adapt in the service layer** (`<app>/src/shared/services/*Service.ts`) with a "
  "thin request/response normalizer; screens should not need to change.")
h2("9.1 Endpoint mapping")
MAP_COLS = ["Frontend proposed", "Actual backend", "App", "Main difference", "Required frontend change"]
MAP_W = [4.2, 8.2, 1.6, 5.6, 6.3]
table(MAP_COLS, [
    ["POST /auth/otp/send", "POST /api/v1/customer/auth/otp/request\nPOST /api/v1/customer/registration/otp/request\nPOST /api/v1/merchant/auth/otp/request", "Both", "Route decides the app (no appTarget). Status 202, not 200. Body field `mobile_number`. Response `request_id`, `expires_in`, `resend_after`; no `devOtp`. Never 403 WRONG_APP or USER_INACTIVE: unknown, blocked and wrong-app numbers get 202 with no SMS.", "Update endpoint mapping; rename fields in an adapter; accept 202; remove WRONG_APP / USER_INACTIVE handling at this step; pick the registration or login route explicitly in the Customer app."],
    ["POST /auth/otp/resend", "POST {prefix}/otp/resend", "Both", "Body is `request_id` (no appTarget). Unknown request: 400 OTP_PURPOSE_MISMATCH, not 404. Too early: 429 OTP_RESEND_TOO_SOON with Retry-After.", "Update mapping and error handling."],
    ["POST /auth/otp/verify", "POST {prefix}/otp/verify", "Both", "Body: `request_id`, `otp`, optional `device` (no mobile or appTarget needed). Response: token pair + navigation fields, not `{token, expiresAt, user}`. Unknown request: 400 OTP_PURPOSE_MISMATCH, not 404.", "Adapter builds the app's session object from the new fields; store both tokens; route by next_action."],
    ["(not in spec)", "POST {prefix}/token/refresh", "Both", "Access tokens last 15 minutes and must be refreshed with a single-use refresh token.", "Add a refresh service and single-flight interceptor."],
    ["GET /auth/me", "GET /api/v1/customer/auth/me\nGET /api/v1/customer/registration/me\nGET /api/v1/merchant/auth/me", "Both", "Channel-specific. Returns navigation fields; no `customerStatus`, `customerId`, `appTarget`, `branchName`.", "Call the path that matches the stored session type; map fields in the adapter."],
    ["POST /auth/logout (Bearer, empty body)", "POST {prefix}/logout", "Both", "Body `{ \"refresh_token\": ... }`; no Authorization needed; always 204.", "Send the refresh token; clear tokens regardless of the result."],
    ["(not in spec)", "POST {prefix}/logout-all", "Both", "Bearer; ends all sessions of the user.", "Optional \"Sign out of all devices\" action."],
    ["POST /customers/register (one call with address, documents, sites)", "POST /api/v1/customer/registration/profile, then POST /api/v1/customer/registration/submit", "Customer", "Two calls with an onboarding token. Profile accepts only `merchant_code` (required), `customer_type`, `name`, `gst_number`. Address, email, documents and sites are not accepted. Returns a registration profile, not the spec's `Customer`.", "Update mapping. Collect merchant_code. Keep other form fields locally or hide them until the backend supports them (Product Owner decision)."],
    ["GET /customers/me", "GET /api/v1/customer/registration/profile (onboarding)\n`customer_profile` in GET /api/v1/customer/auth/me (full)", "Customer", "No full Customer profile endpoint with address, documents, balance or pricing tier.", "Use the summary from /me; full profile is pending backend work."],
    ["(status screen from `customerStatus`)", "GET /api/v1/customer/registration/status", "Customer", "Returns `status`, `message`, `next_action`, `rejection_reason`.", "Map to the status screen."],
    ["GET /kyc/applications", "GET /api/v1/merchant/customers?status=UNDER_REVIEW", "Merchant", "Returns `{items: [...]}` of registration profiles (no documents, address or sites). Permission `customers.view`, not `customers.kyc.review`.", "Update mapping; unwrap `items`."],
    ["GET /kyc/applications/{id}", "Not available", "Merchant", "No detail endpoint.", "Use the list item. Pending backend work if needed."],
    ["POST /kyc/applications/{id}/decision (APPROVE)", "POST /api/v1/merchant/customers/{customer_id}/approve", "Merchant", "Separate route, no body. Permission `customers.approve`. Returns the updated registration profile.", "Update mapping."],
    ["POST /kyc/applications/{id}/decision (REJECT)", "POST /api/v1/merchant/customers/{customer_id}/reject", "Merchant", "Body `{ \"reason\": ... }` (3–500 characters), not `rejectionReason` (spec: 10 or more). Permission `customers.reject`.", "Rename field; keep the app's minimum length or align to 3."],
    ["POST /customers (staff adds customer)", "Not available", "Merchant", "Not implemented.", "Keep mocked or hide."],
    ["GET /customers, /customers/{id}, /customers/{id}/eligibility", "Not available", "Merchant", "Out of scope of this handover; not implemented.", "Keep mocked."],
    ["POST /documents, GET /documents/{fileId}/url", "Not available", "Both", "Document upload is pending backend development.", "Keep mocked; do not enable real KYC."],
], MAP_W, landscape=True, font=7.5)

h2("9.2 Field and behaviour differences")
table(["Topic", "Frontend specification", "Backend (actual)", "Required change"], [
    ["Mobile field", "`mobile` (10 digits)", "`mobile_number`: 10-digit Indian number starting 6–9; `+91`/`91`, spaces and dashes accepted. Returned as `+91XXXXXXXXXX`.", "Rename in adapter; strip `+91` for display if needed."],
    ["Request ID", "`requestId`", "`request_id`", "Rename."],
    ["Timers", "`expiresInSeconds` (120), `resendAfterSeconds` (30)", "`expires_in` (300 in the tested configuration), `resend_after` (30 in the tested configuration). Values are backend settings.", "Rename; read the values instead of hard-coding them."],
    ["Development OTP", "`devOtp` in the response", "Not returned. Local development uses a fixed code configured in the backend `.env`.", "Remove `devOtp` use."],
    ["App identity", "`appTarget` in the body; 403 WRONG_APP", "Route prefix decides the app. Tokens from another app: 401 TOKEN_CHANNEL_MISMATCH. No WRONG_APP code.", "Stop sending appTarget; choose the prefix per app."],
    ["Token", "One `token` + `expiresAt`", "`token.access_token`, `token.refresh_token`, `token.token_type` (Bearer), `token.expires_in` (seconds).", "Store both; compute expiry locally."],
    ["User object", "`user`: id, mobile, name, role, permissions, status, appTarget, customerId, customerStatus, branchName", "Flat fields: `user_id`, `role`, `active_roles`, `account_status`, `approval_status`, `profile_completion_status`, `next_action`, `merchant`, `customer_profile`, `delivery_profile`. Name, mobile and `effective_permissions` are returned by `/me` only.", "Adapter maps to the app's AuthUser; call `/me` after verify if name or permissions are needed."],
    ["Roles", "`CUSTOMER`, `MANAGER`, `SALESPERSON`, `GODOWN_INCHARGE`, `ACCOUNTANT`", "Lower-case role codes: `customer`, `manager`, `salesperson`, `godown_stock_manager`, `accountant` (and custom roles).", "Map codes; `GODOWN_INCHARGE` ↔ `godown_stock_manager` must be confirmed."],
    ["Permissions", "`dashboard.view`, `customers.kyc.review`, `delivery.confirm`, `inventory.view`, `payments.record`, ...", "Backend codes differ (for example `customers.review/approve/reject`, `deliveries.view`, `payments.collect`). The seeded Manager role holds only `delivery_users.*` permissions.", "Do not gate Merchant screens on the spec names; agree a mapping. TO BE CONFIRMED FROM OPENAPI OR BACKEND CODE for non-auth modules."],
    ["Customer state", "`customerStatus`: NEW, PENDING, APPROVED, REJECTED, SUSPENDED", "`next_action` plus `approval_status` (NOT_SUBMITTED, PENDING, APPROVED, REJECTED, SUSPENDED) and `customer_profile.status`.", "Route by next_action. A suggested adapter mapping: NOT_SUBMITTED → NEW; PENDING → PENDING; others unchanged (to be agreed)."],
    ["User status", "ACTIVE, INACTIVE; 403 USER_INACTIVE", "`account_status`: PENDING, ACTIVE, INACTIVE, BLOCKED. 403 ACCOUNT_INACTIVE / ACCOUNT_BLOCKED.", "Map codes."],
    ["Wrong attempts", "3 wrong attempts; then OTP_EXPIRED", "5 wrong attempts per code (OTP_ATTEMPTS_EXCEEDED); 10 wrong codes per hour per number (429 OTP_LOCKED).", "Handle the new codes."],
    ["Unknown customer", "Login creates a NEW user", "Customer login never creates users. Registration uses `/customer/registration/*` and returns an onboarding session.", "Separate registration and login services."],
    ["Error envelope", "`{message, code, fieldErrors: {field: text}}`", "`{\"detail\": {code, message, fields: [{field, code, message}], request_id}}`", "Normalizer converts `fields[]` to the app's `fieldErrors`."],
    ["Idempotency", "Idempotency-Key header proposed", "Not used by authentication routes.", "None for auth."],
    ["Money, orders, pricing", "Specified", "Not part of this handover.", "Keep mocked."],
], [2.6, 5.2, 9.6, 7.9], landscape=True, font=7.5)

# ---------------------------------------------------------------------------------------------
h1("10. Field-level contracts")
p("Common rules: `Content-Type: application/json`; optional `X-Request-ID` (8–64 characters from "
  "letters, digits, `.`, `_`, `-`), echoed in the response header and in error bodies. Timestamps without "
  "an offset are UTC. `{prefix}` is `/api/v1/merchant/auth`, `/api/v1/customer/auth` or "
  "`/api/v1/customer/registration`.")

h2("10.1 Request OTP: POST {prefix}/otp/request")
table(["Field", "Type", "Required", "Validation"], [
    ["mobile_number", "string", "Yes", "Indian mobile: 10 digits starting 6–9; `+91`/`91`, spaces, dashes allowed; 6–15 characters."],
    ["country_code", "string", "No", "`+91` (default) or `91`."],
    ["device.device_id", "string", "Recommended", "Up to 100 characters; stable install ID; used for per-device limits."],
    ["device.device_type", "string", "No", "Up to 20 characters (`android`, `ios`)."],
    ["device.device_name", "string", "No", "Up to 100 characters."],
    ["device.app_version", "string", "No", "Up to 40 characters."],
    ["device.fcm_token", "string", "No", "Up to 512 characters; ignored on this route (send it on verify)."],
    ["login_channel", "string", "No", "Deprecated and ignored."],
], [3.4, 1.6, 2.2, 10.0])
p("Success: **202**. The same response is returned for every valid number; codes are sent only to "
  "accounts that may use this app.")
code("""
POST /api/v1/merchant/auth/otp/request
{"mobile_number": "<masked-mobile>",
 "device": {"device_id": "<install-id>", "device_type": "android", "app_version": "1.0.0"}}

202 Accepted
{"request_id": "<request-id>", "message": "OTP request accepted",
 "expires_in": 300, "resend_after": 30, "code": "OTP_REQUEST_ACCEPTED"}
""")
p("Errors: 422 INVALID_MOBILE_NUMBER or VALIDATION_ERROR · 429 OTP_RATE_LIMITED or OTP_LOCKED (with "
  "Retry-After) · 503 OTP_DELIVERY_FAILED (with Retry-After). The OpenAPI file still lists 404 for this "
  "route; the backend no longer returns it (see section 11, contract difference CD-01).")
code("""
429 Too Many Requests        Retry-After: 1800
{"detail": {"code": "OTP_RATE_LIMITED",
            "message": "Too many codes requested. Try again later.",
            "fields": [], "request_id": "<request-id>"}}
""")
p("Mobile behaviour: show the code screen with the expiry and resend timers. Word it as \"If this number is "
  "registered, we sent a code\". Disable the button for Retry-After seconds on 429 and 503.")

h2("10.2 Resend OTP: POST {prefix}/otp/resend")
table(["Field", "Type", "Required", "Validation"], [
    ["request_id", "string", "Yes", "1–36 characters; the latest request_id from request or resend on the same prefix."],
    ["device", "object", "No", "As in 10.1."],
], [3.4, 1.6, 2.2, 10.0])
p("Success: **202**, same body as 10.1 with a **new** `request_id`. Earlier codes stop working.")
p("Errors: 400 OTP_PURPOSE_MISMATCH (unknown ID or ID from another prefix) · 400 OTP_ALREADY_USED · "
  "403 CHANNEL_NOT_ALLOWED (declared; not expected in practice) · 422 VALIDATION_ERROR · 429 "
  "OTP_RESEND_TOO_SOON, OTP_RATE_LIMITED or OTP_LOCKED (Retry-After) · 503 OTP_DELIVERY_FAILED.")
p("Mobile behaviour: replace the stored request_id; restart both timers.")

h2("10.3 Verify OTP: POST {prefix}/otp/verify")
table(["Field", "Type", "Required", "Validation"], [
    ["request_id", "string", "Yes", "1–36 characters."],
    ["otp", "string", "Yes", "Digits only, exactly the configured length (currently 4). Send as a string to keep leading zeros."],
    ["device", "object", "Recommended", "device_id, device_type, device_name, app_version and fcm_token are stored on the new session."],
    ["mobile_number, country_code, login_channel", "-", "No", "Deprecated and ignored."],
], [3.4, 1.6, 2.2, 10.0])
table(["Response field", "Type", "Notes"], [
    ["token.access_token / token.refresh_token", "string", "JWTs. Store securely."],
    ["token.token_type", "string", "`Bearer`."],
    ["token.expires_in", "integer", "Access-token lifetime in seconds (900)."],
    ["user_id", "string", "User ID."],
    ["login_channel", "string", "`MERCHANT` or `CUSTOMER`."],
    ["user_type", "string", "`MERCHANT_STAFF` or `CUSTOMER`."],
    ["session_type", "string", "`access` or `onboarding`."],
    ["role / active_roles", "string / string[]", "Primary role code and distinct role codes for this app."],
    ["account_status", "string", "User status: PENDING, ACTIVE, INACTIVE, BLOCKED."],
    ["approval_status", "string or null", "Merchant: the merchant's approval status. Customer: NOT_SUBMITTED, PENDING, APPROVED, REJECTED or SUSPENDED."],
    ["profile_completion_status", "string or null", "Customer only: NOT_STARTED, INCOMPLETE, COMPLETE."],
    ["next_action", "string", "See section 13."],
    ["merchant", "object or null", "Merchant App: id, code, name, status, approval_status, staff_type."],
    ["customer_profile", "object or null", "Customer App: id, customer_type, name, merchant_code, status, rejection_reason, submitted_at."],
    ["delivery_profile", "object or null", "Delivery App only; always null for these apps."],
    ["is_new_user", "boolean", "True only when registration verification created the account."],
    ["code / message", "string", "`OTP_VERIFIED` / `OTP verified`."],
], [5.4, 3.0, 8.8], font=8)
code("""
200 OK   (POST /api/v1/merchant/auth/otp/verify)
{"token": {"access_token": "<access-token>", "refresh_token": "<refresh-token>",
           "token_type": "Bearer", "expires_in": 900},
 "user_id": "<user-id>", "login_channel": "MERCHANT", "user_type": "MERCHANT_STAFF",
 "session_type": "access", "role": "manager", "active_roles": ["manager"],
 "account_status": "ACTIVE", "approval_status": "APPROVED",
 "profile_completion_status": null, "next_action": "OPEN_MERCHANT_HOME",
 "merchant": {"id": "<merchant-id>", "code": "<merchant-code>", "name": "<business-name>",
              "status": "ACTIVE", "approval_status": "APPROVED",
              "staff_type": "PRIMARY_MANAGER"},
 "delivery_profile": null, "customer_profile": null,
 "is_new_user": false, "code": "OTP_VERIFIED", "message": "OTP verified"}
""")
code("""
200 OK   (POST /api/v1/customer/registration/otp/verify, new number)
{"token": {"access_token": "<onboarding-access-token>",
           "refresh_token": "<refresh-token>", "token_type": "Bearer", "expires_in": 900},
 "user_id": "<user-id>", "login_channel": "CUSTOMER", "user_type": "CUSTOMER",
 "session_type": "onboarding", "role": null, "active_roles": [],
 "account_status": "PENDING", "approval_status": "NOT_SUBMITTED",
 "profile_completion_status": "NOT_STARTED", "next_action": "COMPLETE_PROFILE",
 "merchant": null, "delivery_profile": null, "customer_profile": null,
 "is_new_user": true, "code": "OTP_VERIFIED", "message": "OTP verified"}
""")
p("Errors: 400 OTP_INVALID, OTP_EXPIRED, OTP_ATTEMPTS_EXCEEDED, OTP_ALREADY_USED, OTP_PURPOSE_MISMATCH · "
  "403 account codes (only if the account changed after the code was sent) · 404 NUMBER_NOT_REGISTERED "
  "(rare) · 422 VALIDATION_ERROR (including wrong code length) · 429 RATE_LIMITED or OTP_LOCKED.")
code("""
400 Bad Request
{"detail": {"code": "OTP_INVALID",
            "message": "The code is incorrect. Check the code and try again.",
            "fields": [], "request_id": "<request-id>"}}
""")
p("Mobile behaviour: store both tokens atomically, then navigate by `next_action`. On OTP_INVALID keep the "
  "code screen. The same code is returned when the number has no access to this app.")

h2("10.4 Refresh: POST {prefix}/token/refresh")
table(["Field", "Type", "Required", "Validation"], [
    ["refresh_token", "string", "Yes", "Latest refresh token issued by the same prefix; single use."],
    ["device", "object", "No", "Send when the push token or app version changed; omitted values are copied from the current session."],
    ["device_id", "string", "No", "Deprecated; use device.device_id."],
], [3.4, 1.6, 2.2, 10.0])
code("""
200 OK
{"access_token": "<access-token>", "refresh_token": "<refresh-token>",
 "token_type": "Bearer", "expires_in": 900}
""")
p("Errors: 401 SESSION_REVOKED, SESSION_EXPIRED, TOKEN_INVALID, TOKEN_TYPE_NOT_ALLOWED, "
  "TOKEN_CHANNEL_MISMATCH · 403 account codes · 422 VALIDATION_ERROR. "
  "A registration refresh token is rejected on `/api/v1/customer/auth/token/refresh` (401 TOKEN_TYPE_NOT_ALLOWED) and vice versa.")
p("Mobile behaviour: replace both tokens; the previous access token stops working immediately.")

h2("10.5 Current user: GET {prefix}/me")
p("Header `Authorization: Bearer <access-token>`. Returns the fields of 10.3 (without `token`, `is_new_user`, "
  "`code`, `message`) plus:")
table(["Field", "Type", "Notes"], [
    ["display_name", "string or null", "Full name, username or number."],
    ["mobile_number", "string", "`+91XXXXXXXXXX`; mask it in logs."],
    ["country_code", "string", "`+91`."],
    ["effective_permissions", "string[]", "Backend permission codes for this app."],
    ["status", "string", "Deprecated; same as account_status."],
    ["profile", "object or null", "Deprecated; use customer_profile."],
], [4.0, 3.0, 10.2])
code("""
200 OK   (GET /api/v1/customer/auth/me)
{"user_id": "<user-id>", "display_name": "<name>", "mobile_number": "<masked-mobile>",
 "country_code": "+91", "login_channel": "CUSTOMER", "user_type": "CUSTOMER",
 "session_type": "access", "role": "customer", "active_roles": ["customer"],
 "effective_permissions": [], "account_status": "ACTIVE", "approval_status": "APPROVED",
 "profile_completion_status": "COMPLETE", "next_action": "OPEN_CUSTOMER_HOME",
 "merchant": null, "delivery_profile": null,
 "customer_profile": {"id": "<customer-id>", "customer_type": "RETAIL",
   "name": "<business-name>", "merchant_code": "<merchant-code>",
   "status": "APPROVED", "rejection_reason": null, "submitted_at": "<timestamp>"},
 "status": "ACTIVE", "profile": {"...": "same as customer_profile"}}
""")
p("Errors: 401 AUTH_REQUIRED, TOKEN_INVALID, TOKEN_EXPIRED, TOKEN_TYPE_NOT_ALLOWED, TOKEN_CHANNEL_MISMATCH, "
  "SESSION_REVOKED, SESSION_EXPIRED · 403 account codes (ACCOUNT_BLOCKED, MERCHANT_BLOCKED, ...).")

h2("10.6 Logout: POST {prefix}/logout and logout-all: POST {prefix}/logout-all")
table(["Route", "Auth", "Body", "Success", "Errors"], [
    ["logout", "None", "`{\"refresh_token\": \"<refresh-token>\"}` (optional)", "204, always (also for missing, invalid, already-revoked or other-app tokens)", "422 only for malformed JSON"],
    ["logout-all", "Bearer access (onboarding token on the registration prefix)", "None", "204", "401 token codes · 403 account codes"],
], [2.2, 3.6, 4.4, 4.0, 3.0], font=8)
p("Mobile behaviour: clear tokens and local push registration even if the call fails.")

h2("10.7 Check mobile: POST /api/v1/customer/auth/check-mobile")
code("""
Request:  {"mobile_number": "<masked-mobile>"}
200 OK    {"code": "NUMBER_NOT_REGISTERED",
           "message": "Mobile number is not registered. Registration may be started.",
           "registered": false, "registration_allowed": true}
200 OK    {"code": "MOBILE_REGISTERED", "message": "Mobile number is registered.",
           "registered": true, "registration_allowed": false}
""")
p("`registered: true` means a registration draft exists, not that the customer is approved. "
  "Errors: 422 INVALID_MOBILE_NUMBER · 429 RATE_LIMITED (Retry-After).")

h2("10.8 Registration fields: GET /api/v1/customer/registration/fields")
p("No authentication. Returns `fields[]` with `api_field_name`, `display_label`, `data_type`, `required`, "
  "`source`, `allowed_values` and `required_for` (`create` or `submit`). Current fields: mobile_number, "
  "customer_type (RETAIL, INDUSTRIAL), merchant_code, name, gst_number.")

h2("10.9 Registration profile: POST, GET and PATCH /api/v1/customer/registration/profile")
table(["Field", "Type", "Create", "Before submit", "Validation"], [
    ["merchant_code", "string", "Required", "Required", "1–80 characters; case-insensitive; must be an active, approved merchant (else 422 MERCHANT_CODE_INVALID)."],
    ["customer_type", "string", "Optional", "Required", "RETAIL or INDUSTRIAL (case-insensitive)."],
    ["name", "string", "Optional", "Required", "2–160 characters."],
    ["gst_number", "string", "Optional", "Optional", "Up to 30 characters (format not validated)."],
    ["mobile_number", "string", "Optional", "-", "Ignored if equal to the verified number; a different number returns 403 PERMISSION_DENIED."],
], [2.8, 1.5, 1.8, 2.2, 8.9], font=8)
code("""
POST /api/v1/customer/registration/profile
Authorization: Bearer <onboarding-access-token>
{"merchant_code": "<merchant-code>", "customer_type": "RETAIL", "name": "<business-name>"}

201 Created
{"id": "<customer-id>", "mobile_number": "<masked-mobile>", "merchant_id": "<merchant-id>",
 "merchant_code": "<merchant-code>", "customer_type": "RETAIL", "name": "<business-name>",
 "gst_number": null, "status": "PROFILE_INCOMPLETE", "rejection_reason": null,
 "submitted_at": null, "created_at": "<timestamp>", "updated_at": "<timestamp>"}
""")
table(["Operation", "Success", "Errors"], [
    ["POST (create)", "201 profile", "401 token codes · 403 PERMISSION_DENIED, ACCOUNT_BLOCKED · 409 REGISTRATION_PROFILE_EXISTS · 422 VALIDATION_ERROR, MERCHANT_CODE_INVALID, INVALID_MOBILE_NUMBER"],
    ["GET (read)", "200 profile", "401 · 403 · 404 REGISTRATION_PROFILE_NOT_FOUND"],
    ["PATCH (update any subset)", "200 profile", "401 · 403 · 404 · 409 REGISTRATION_NOT_EDITABLE (only PROFILE_INCOMPLETE, DOCUMENTS_PENDING or REJECTED can change) · 422"],
], [3.6, 2.6, 11.0], font=8)
callout("info", "Contract difference: the frontend registration form also collects business and owner names, "
        "email, delivery address, KYC documents and industrial sites. The backend does not accept these "
        "fields yet (Product Owner decision required, section 17).")

h2("10.10 Submit: POST /api/v1/customer/registration/submit")
code("""
200 OK
{"status": "UNDER_REVIEW", "message": "Your registration is being reviewed.",
 "next_action": "WAIT_FOR_APPROVAL", "rejection_reason": null}

422 Unprocessable
{"detail": {"code": "REGISTRATION_INCOMPLETE",
  "message": "Complete all required registration details first.",
  "fields": [{"field": "name", "code": "missing",
              "message": "This field is required before submitting."}],
  "request_id": "<request-id>"}}
""")
p("No body. Repeating the call while UNDER_REVIEW returns 200. Errors: 401 · 403 · 404 "
  "REGISTRATION_PROFILE_NOT_FOUND · 409 INVALID_STATUS_TRANSITION (already approved) · 422 "
  "REGISTRATION_INCOMPLETE or MERCHANT_CODE_INVALID.")

h2("10.11 Status: GET /api/v1/customer/registration/status")
code("""
200 OK
{"status": "REJECTED",
 "message": "Your registration was rejected. Update your details and submit again.",
 "next_action": "COMPLETE_PROFILE", "rejection_reason": "<reviewer-reason>"}
""")
p("`status` is one of NOT_STARTED, PROFILE_INCOMPLETE, DOCUMENTS_PENDING, UNDER_REVIEW, APPROVED, REJECTED, "
  "SUSPENDED. The session always decides whose status is returned; a `mobile_number` query parameter is "
  "ignored. Errors: 401 · 403.")

h2("10.12 Merchant customer review")
table(["Route", "Permission", "Body", "Success", "Errors"], [
    ["GET /api/v1/merchant/customers?status=<status>", "customers.view", "None (status defaults to UNDER_REVIEW)", "200 `{\"items\": [profile, ...]}` (max 200, oldest submission first)", "401 · 403 PERMISSION_DENIED, CHANNEL_NOT_ALLOWED, account codes"],
    ["POST /api/v1/merchant/customers/{customer_id}/approve", "customers.approve", "None", "200 profile (status APPROVED); user activated; `customer` role assigned", "404 CUSTOMER_NOT_FOUND (also for other merchants) · 409 INVALID_STATUS_TRANSITION, DOCUMENTS_PENDING_APPROVAL"],
    ["POST /api/v1/merchant/customers/{customer_id}/reject", "customers.reject", "`{\"reason\": \"<3-500 characters>\"}`", "200 profile (status REJECTED)", "404 · 409 INVALID_STATUS_TRANSITION · 422 (list format, see CD-06)"],
], [8.4, 2.6, 3.2, 4.2, 7.5], landscape=True, font=8)

# ---------------------------------------------------------------------------------------------
h1("11. Contract differences requiring attention")
p("Where sources disagree, the difference is listed instead of choosing one silently.")
table(["ID", "Difference", "Evidence", "Handling"], [
    ["CD-01", "OpenAPI lists 404 for `otp/request`; the backend returns 202 for unknown numbers.", "Generated OpenAPI vs service code and integration tests.", "Treat 404 as not expected. Backend to remove the stale declaration."],
    ["CD-02", "Frontend expects 403 WRONG_APP for staff numbers in the Customer app and vice versa.", "API_SPEC §4.1 vs backend uniform 202 and OTP_INVALID.", "No WRONG_APP code exists. Show a neutral hint after a failed code."],
    ["CD-03", "Frontend logout requires Bearer with an empty body.", "API_SPEC §4.5 vs backend LogoutRequest.", "Send refresh_token in the body."],
    ["CD-04", "Frontend registration is one call with address, documents and sites; backend needs merchant_code and two calls.", "API_SPEC §5.1 vs customers router.", "Product Owner decision on fields; adapter for now."],
    ["CD-05", "Frontend KYC decision uses `rejectionReason` (10 or more characters); backend reject uses `reason` (3–500).", "API_SPEC §8.3 vs CustomerRejectRequest.", "Rename field; agree the minimum length."],
    ["CD-06", "Validation errors on `/api/v1/merchant/customers/*` use FastAPI's list format `{\"detail\": [{type, loc, msg}]}`, not the coded envelope.", "Exception handler applies the coded format only to `/auth/` and `/customer/registration` paths.", "Normalizer must accept both shapes. Backend follow-up recommended."],
    ["CD-07", "Frontend role GODOWN_INCHARGE vs backend role code godown_stock_manager.", "API_SPEC §2 vs backend role seeds.", "Mapping to be confirmed."],
    ["CD-08", "Frontend permission names differ from backend permission codes; seeded Manager has only delivery_users.* permissions.", "API_SPEC §2.1 vs backend permission seeds.", "Agree a mapping before gating Merchant screens."],
    ["CD-09", "Frontend `AuthUser.branchName`; backend returns `merchant.name` and no branch concept.", "API_SPEC §3.2 vs AccountFields schema.", "TO BE CONFIRMED FROM OPENAPI OR BACKEND CODE whether a branch field is needed."],
    ["CD-10", "Frontend OTP 120 s and 3 attempts; backend 300 s (configured) and 5 attempts plus hourly lockout.", "API_SPEC §4 vs backend settings.", "Use response values; handle both codes."],
    ["CD-11", "Default `OTP_RESEND_COOLDOWN_SECONDS` is 60 in code; 30 in the tested configuration and `.env.example`.", "config/app.py vs .env.example.", "Read `resend_after`; DevOps to set the value per environment."],
], [1.4, 6.8, 5.6, 7.0], landscape=True, font=8)

# ---------------------------------------------------------------------------------------------
h1("12. Token handling for mobile developers")
bullets(
    "**Storage:** keep both tokens only in platform-secure storage (iOS Keychain / Android Keystore) through the "
    "project's chosen React Native secure-storage library. Do not use AsyncStorage or unencrypted storage for tokens. "
    "Keep the access token in memory while the app runs.",
    "**Expiry:** the access token lasts `expires_in` seconds (900). Refresh about 60 seconds early or when a request "
    "returns 401 TOKEN_EXPIRED. The refresh token lasts 30 days; its lifetime is not returned.",
    "**Rotation:** every refresh returns a new pair. Write both new tokens before discarding the old ones. The old "
    "access token stops working immediately.",
    "**Reuse:** a refresh token presented again more than 10 seconds after it was used ends the whole sign-in chain "
    "(all devices that descend from that sign-in). Duplicate refreshes within 10 seconds are refused (401) without "
    "signing the user out.",
    "**Concurrency:** use one single-flight refresh. Queue other requests until it finishes; never retry a refresh with the same token in a loop.",
    "**Revocation:** logout, logout-all, admin sign-out and blocks take effect on the next request (401 SESSION_REVOKED or a 403 account code).",
    "**Missing token:** 401 AUTH_REQUIRED. **Invalid token:** 401 TOKEN_INVALID. **Expired access token:** 401 "
    "TOKEN_EXPIRED (refresh once). **Revoked:** 401 SESSION_REVOKED. **Expired sign-in:** 401 SESSION_EXPIRED. "
    "**Other app's token:** 401 TOKEN_CHANNEL_MISMATCH. **Wrong session type:** 401 TOKEN_TYPE_NOT_ALLOWED.",
    "**Onboarding tokens** are limited to registration so that an unapproved applicant can never reach customer data or ordering APIs.",
    "Never log tokens, codes or full mobile numbers. Log the `X-Request-ID` instead.",
)

# ---------------------------------------------------------------------------------------------
h1("13. Mobile navigation contract")
table(["next_action", "App", "Meaning", "Mobile destination", "Session type"], [
    ["OPEN_MERCHANT_HOME", "Merchant", "Account, staff link and merchant are active and approved.", "Merchant home", "access"],
    ["OPEN_CUSTOMER_HOME", "Customer", "Approved customer with an active account and the customer role.", "Customer home", "access"],
    ["COMPLETE_PROFILE", "Customer", "No draft, draft incomplete, or registration rejected.", "Registration form (show rejection_reason)", "onboarding"],
    ["SUBMIT_DOCUMENTS", "Customer", "Draft status DOCUMENTS_PENDING. Not reachable today (no upload API).", "Document upload (future)", "onboarding"],
    ["WAIT_FOR_APPROVAL", "Customer", "Registration under review.", "\"Under review\" screen", "onboarding"],
    ["SIGN_IN", "Customer", "Onboarding session of an approved customer.", "Customer sign-in (7.2)", "onboarding"],
    ["CONTACT_SUPPORT", "Customer", "Registration suspended.", "\"Contact support\" screen", "onboarding"],
], [3.6, 1.8, 5.2, 3.6, 3.0], font=8)
table(["Field", "How to use it"], [
    ["role", "Primary role code for this app (`manager`, `salesperson`, `godown_stock_manager`, `accountant`, `customer`, or a custom code). Null for new registrants."],
    ["user_type", "`MERCHANT_STAFF` or `CUSTOMER` for these apps."],
    ["session_type", "`access` or `onboarding`; decides which routes the token may call."],
    ["account_status", "User account state: PENDING, ACTIVE, INACTIVE, BLOCKED."],
    ["approval_status", "Merchant: merchant approval. Customer: NOT_SUBMITTED, PENDING, APPROVED, REJECTED, SUSPENDED."],
    ["profile_completion_status", "Customer: NOT_STARTED, INCOMPLETE, COMPLETE (name, customer_type and merchant_code present)."],
    ["is_new_user", "Verify response only; true when registration verification created the account."],
    ["merchant", "Merchant summary for header and scoping."],
    ["customer_profile", "Customer summary including status and rejection_reason."],
    ["effective_permissions", "`/me` only. Use to show or hide features; the backend authorizes every call anyway."],
], [4.0, 13.2], font=8.5)
callout("info", "Route by `next_action`. Do not infer navigation from null fields or by combining status fields yourself. "
        "A successful (200) verify or /me response for the Merchant App always carries OPEN_MERCHANT_HOME: accounts that may "
        "not use the app never receive a code, and a state change after sign-in is reported as a 403 error code "
        "(section 14), which the app maps to its waiting or contact-support screen.")

# ---------------------------------------------------------------------------------------------
h1("14. Error contract")
code("""
{"detail": {"code": "AUTH_REQUIRED",
            "message": "Sign in to continue.",
            "fields": [],
            "request_id": "<request-id>"}}
""")
bullets(
    "Application logic must use `detail.code`. `detail.message` is safe to display but may change.",
    "Validation errors list fields: `fields: [{\"field\": \"device.device_id\", \"code\": \"string_too_long\", \"message\": \"...\"}]`.",
    "A 401 does not always mean the same thing; branch on the code.",
    "Respect `Retry-After` on 429 and 503.",
    "Unexpected failures return 500 INTERNAL_ERROR without internal details.",
    "Exception: validation errors on `/api/v1/merchant/customers/*` use FastAPI's list format (CD-06).",
)
table(["HTTP", "Code", "Meaning", "Mobile behaviour"], [
    ["401", "AUTH_REQUIRED", "No Bearer token sent.", "Go to sign-in."],
    ["401", "TOKEN_EXPIRED", "Access token expired.", "Refresh once, retry."],
    ["401", "TOKEN_INVALID", "Malformed or tampered token.", "Clear tokens, sign in."],
    ["401", "TOKEN_TYPE_NOT_ALLOWED", "Wrong session type for this route.", "Clear tokens, start the right flow."],
    ["401", "TOKEN_CHANNEL_MISMATCH", "Token from another app.", "Clear tokens, sign in."],
    ["401", "SESSION_REVOKED", "Signed out or session replaced.", "Clear tokens, sign in (no error dialog)."],
    ["401", "SESSION_EXPIRED", "Sign-in older than 30 days, or refresh token expired.", "Sign in."],
    ["400", "OTP_INVALID", "Wrong code, or number has no access to this app.", "Stay on code screen."],
    ["400", "OTP_EXPIRED", "Code expired.", "Offer resend."],
    ["400", "OTP_ATTEMPTS_EXCEEDED", "5 wrong entries for this code.", "Offer resend."],
    ["400", "OTP_ALREADY_USED", "Code used or replaced.", "Request a new code."],
    ["400", "OTP_PURPOSE_MISMATCH", "Unknown request_id or from another flow.", "Restart from number screen."],
    ["403", "CHANNEL_NOT_ALLOWED", "Declared on resend/verify; on merchant review routes, token from another channel.", "Restart / sign in."],
    ["404", "NUMBER_NOT_REGISTERED", "Account removed after the code was sent (rare).", "Show \"No account found\"."],
    ["422", "INVALID_MOBILE_NUMBER", "Not a valid Indian mobile number.", "Highlight field."],
    ["422", "VALIDATION_ERROR", "Invalid fields (see `fields`).", "Highlight fields."],
    ["429", "OTP_RESEND_TOO_SOON", "Resend cooldown running.", "Wait Retry-After."],
    ["429", "OTP_RATE_LIMITED", "Too many codes for number, device or IP.", "Disable for Retry-After."],
    ["429", "OTP_LOCKED", "10 wrong codes in an hour for this number.", "Disable sign-in for Retry-After."],
    ["429", "RATE_LIMITED", "Too many verifications or check-mobile calls from this IP.", "Wait Retry-After."],
    ["503", "OTP_DELIVERY_FAILED", "SMS could not be sent (always, outside local, until a vendor exists).", "Retry after Retry-After; show a clear message."],
    ["403", "ACCOUNT_BLOCKED", "User or staff link blocked.", "Contact support; clear tokens."],
    ["403", "ACCOUNT_INACTIVE", "Account not active.", "Contact support."],
    ["403", "ACCOUNT_PENDING_APPROVAL", "Merchant or customer not yet approved.", "Waiting screen."],
    ["403", "ACCOUNT_REJECTED", "Merchant or customer rejected.", "Contact support (customer: correct and resubmit)."],
    ["403", "ACCOUNT_SUSPENDED", "Customer suspended.", "Contact support."],
    ["403", "DOCUMENTS_PENDING_APPROVAL", "Customer documents not yet approved; also 409 on approve.", "Waiting screen."],
    ["403", "MERCHANT_BLOCKED", "The business is blocked.", "Contact MBGA support."],
    ["403", "MERCHANT_INACTIVE", "The business is not active.", "Contact MBGA support."],
    ["403", "ROLE_NOT_ASSIGNED", "No role for this app.", "Contact administrator."],
    ["403", "PERMISSION_DENIED", "Missing permission, or submitted mobile number is not the verified one.", "Hide the action / show message."],
    ["404", "REGISTRATION_PROFILE_NOT_FOUND", "No registration draft.", "Show registration form."],
    ["409", "REGISTRATION_PROFILE_EXISTS", "Draft already exists.", "Load it with GET."],
    ["409", "REGISTRATION_NOT_EDITABLE", "Under review or approved.", "Show status."],
    ["409", "INVALID_STATUS_TRANSITION", "Action not allowed in current state.", "Reload status."],
    ["422", "REGISTRATION_INCOMPLETE", "Required fields missing before submit.", "Highlight `fields`."],
    ["422", "MERCHANT_CODE_INVALID", "Unknown or inactive merchant code.", "Highlight merchant code."],
    ["404", "CUSTOMER_NOT_FOUND", "Application not in the reviewer's merchant.", "Refresh list."],
    ["500", "INTERNAL_ERROR", "Unexpected failure.", "Generic error with request ID."],
], [1.3, 5.0, 6.0, 4.9], font=8)

# ---------------------------------------------------------------------------------------------
h1("15. Breaking contract changes")
table(["Change", "Previous frontend assumption", "Current backend behaviour", "Required mobile update"], [
    ["Unknown numbers", "404 or 403 for unknown / wrong-app numbers", "202 for every valid number; no SMS; verify returns 400 OTP_INVALID", "Neutral code-screen wording; no \"not registered\" branch after request"],
    ["Missing token", "401 (generic)", "401 AUTH_REQUIRED (previously SESSION_EXPIRED)", "Branch on code"],
    ["Token errors", "One 401 meaning", "TOKEN_INVALID, TOKEN_EXPIRED, TOKEN_CHANNEL_MISMATCH, TOKEN_TYPE_NOT_ALLOWED, SESSION_REVOKED, SESSION_EXPIRED", "Refresh only on TOKEN_EXPIRED; otherwise sign out"],
    ["role", "Enum; previously always null", "Lower-case role code string", "Map role codes"],
    ["Registration auth", "Profile and status without token (status by mobile number)", "Onboarding Bearer token required; number taken from session", "Send onboarding token"],
    ["Messages", "Human-readable text used for logic", "User-facing sentences that may change", "Use `detail.code` only"],
    ["Tokens", "Single token", "Access + refresh pair with rotation", "Store both; single-flight refresh"],
    ["Paths", "Generic `/auth/*`, `/customers/*`", "Channel-specific `/api/v1/{customer|merchant}/...`", "Update service-layer mapping"],
    ["Field names", "camelCase", "snake_case", "Adapter/normalizer"],
    ["Logout", "Client-side only / Bearer", "Server-side session revoked; refresh_token in body; old access token rejected immediately", "Send refresh token; clear local tokens"],
    ["Error body", "`{message, code, fieldErrors}`", "`{detail: {code, message, fields[], request_id}}`", "Normalizer"],
    ["Rate limits", "Per mobile only", "Per number, device and IP; OTP_LOCKED; Retry-After", "Handle 429 generically"],
], [2.6, 4.2, 5.6, 4.8], font=8)

# ---------------------------------------------------------------------------------------------
h1("16. Security and reliability controls")
table(["Control", "Implementation"], [
    ["Hashed OTP storage", "Only a pbkdf2 hash is stored; codes are never returned or logged."],
    ["OTP expiry and resend cooldown", "Configured values (300 s and 30 s in the tested configuration); a new request cancels earlier codes."],
    ["Attempt limits", "5 wrong entries per code; 10 wrong codes per number per hour (OTP_LOCKED)."],
    ["Request limits (per hour)", "5 codes per number per app; 20 code requests per IP; 10 per device ID; 60 verifications per IP; 30 check-mobile calls per IP (defaults). Stored in the database, shared by all instances."],
    ["Enumeration resistance", "Uniform 202 on code requests; no SMS to ineligible numbers. check-mobile still reveals registration existence (rate-limited)."],
    ["Refresh-token hashing and rotation", "SHA-256 hash stored; single use; family revocation on reuse after a 10-second grace window."],
    ["Session validation and channel binding", "Every Bearer request checks session, user, app channel, session type and account state."],
    ["Token-type restriction", "Onboarding tokens only on registration routes; refresh tokens never accepted as access tokens."],
    ["Audit logging", "Sign-in events with masked mobile (last 4 digits), SHA-256 of device ID and client IP; never codes or tokens."],
    ["Security headers and no-store", "X-Request-ID, nosniff, frame denial, referrer policy, CSP on API responses; Cache-Control: no-store on auth and registration responses; HSTS outside local."],
    ["Startup guards", "Outside local/test: strong signing secret required; DEBUG, mock SMS provider and fixed development code refused; API docs off unless enabled. Rejected values are not printed."],
    ["Client IP", "Taken from X-Forwarded-For only when the peer is a configured trusted proxy (TRUSTED_PROXY_IPS must be set in production)."],
], [4.6, 12.6], font=8.5)

# ---------------------------------------------------------------------------------------------
h1("17. Testing evidence")
p("Figures from the backend implementation report of 17 September 2026. Tests ran against the local "
  "development configuration and a disposable test database.")
table(["Test area", "Result", "Confidence", "Follow-up"], [
    ["Backend automated tests", "247 passed", "High", "Investigate one unexplained failure seen in one earlier full run."],
    ["Database-backed authentication tests", "87 passed (real app against the test database)", "High", "None."],
    ["Migration downgrade and upgrade", "Passed (0008–0010 exercised)", "High", "Run on staging before deployment."],
    ["Live authentication check (local)", "27 of 27 steps passed on a temporary server with the development database", "Medium-high", "Repeat on the restarted main server."],
    ["Intermittent failure", "One full backend run had 1 unidentified failure; three reruns passed", "Medium", "Backend to identify the test if it recurs."],
    ["Slow run", "One rerun took about 29 minutes instead of about 50 seconds", "Medium", "Backend to investigate (possible database lock wait)."],
    ["Lint (changed files)", "Passed", "High", "None."],
    ["Frontend web panel type-check and lint", "Passed", "High", "None."],
    ["Frontend web panel unit tests", "135 of 136 passed", "Medium", "Existing Admin security test (\"View admin dashboard\") still fails; unrelated to authentication changes."],
    ["Playwright end-to-end tests", "Not run", "Low", "Run after restarting the backend server."],
    ["Customer and Merchant mobile apps", "Not tested against the backend", "Not available", "Mobile teams to run integration tests."],
], [4.4, 5.2, 2.4, 5.2], font=8)
callout("warning", "The local backend server on port 8005 was still serving code from before these changes. "
        "Restart it before any integration testing.")

# ---------------------------------------------------------------------------------------------
h1("18. Database and migration changes")
table(["Migration", "Purpose (verified from the migration files)"], [
    ["20260917_0008", "Adds `login_channel`, `session_type` and `revoked_reason` to `login_sessions`, plus an index on user and revocation time. Existing sessions keep null values and continue to work."],
    ["20260917_0009", "Adds refresh-token family tracking (`family_id`, `rotated_at`) to sessions; `dispatch_suppressed` and IP/mobile indexes to `otp_challenges`; the new `auth_throttle_events` table for shared rate limits; and authentication audit columns (channel, result, reason code, masked mobile, device hash, IP) to `audit_logs`."],
    ["20260917_0010", "Adds `device_type`, `device_name`, `app_version` and `push_token` to sessions, and `delivery_status`, `delivery_provider` and `delivery_reference` to `otp_challenges`."],
], [3.2, 14.0], font=8.5)
p("All three migrations are additive, have working downgrades, and have been applied to the local "
  "development and test databases. Nothing has been committed to version control.")

# ---------------------------------------------------------------------------------------------
h1("19. Pending items and limitations")
table(["Item", "Current status", "Impact", "Owner", "Required next step", "Blocks"], [
    ["Real SMS vendor integration", "Blocked by external configuration; provider interface, timeout, retry and guards exist", "Outside local, code requests return 503; no real sign-in", "Product Owner (vendor); Backend (integration); DevOps (credentials)", "Select vendor; implement vendor dispatch; configure credentials", "Staging and production sign-in"],
    ["Customer KYC document upload", "Pending backend development", "Registration cannot meet SRS document rules", "Backend; Product Owner (storage)", "Build upload API, storage, masked Aadhaar", "Real Customer approval"],
    ["Customer approval permissions", "Blocked by business decision", "Review endpoints unusable", "Product Owner; Backend (seed/assign)", "Decide roles; assign customers.view/approve/reject", "Merchant review screens"],
    ["Registration fields (address, email, owner, sites)", "Blocked by business decision", "Frontend form fields not stored", "Product Owner; Backend", "Decide scope; extend profile API", "Complete registration"],
    ["Customer suspension and reinstatement", "Blocked by business decision", "No API; ACCOUNT_SUSPENDED only via support", "Product Owner", "Decide scope", "Suspension features"],
    ["SMS to blocked or unapproved users", "Blocked by business decision", "These users see only OTP_INVALID", "Product Owner", "Decide whether to send an explanatory SMS", "Account-state messaging"],
    ["Permission and role mapping", "Blocked by business decision", "Merchant screens cannot rely on spec names", "Product Owner; Backend; Merchant App Team", "Agree codes and role grants", "Merchant feature gating"],
    ["Trusted proxy configuration", "Blocked by external configuration", "All users could share one IP limit", "DevOps", "Set TRUSTED_PROXY_IPS", "Production"],
    ["Backend server restart", "Pending", "Old code served on port 8005", "Backend", "Restart the server", "Integration testing"],
    ["Playwright E2E", "Pending", "Web panel E2E unverified", "Backend", "Run after restart", "Release sign-off"],
    ["Intermittent / slow test", "Pending", "Test reliability", "Backend", "Investigate", "CI confidence"],
    ["Merchant review validation format (CD-06)", "Pending backend development", "Two error shapes", "Backend", "Apply coded envelope to review routes", "None (normalizer handles both)"],
    ["check-mobile enumeration trade-off", "Implemented with limitations", "Reveals whether a registration exists", "Product Owner", "Accept or redesign", "None"],
], [3.4, 3.8, 3.8, 3.8, 4.4, 3.4], landscape=True, font=7.5)

# ---------------------------------------------------------------------------------------------
h1("20. Mobile team action checklist")
h2("20.1 Customer App Team")
bullets(
    "Replace mock authentication calls with `/api/v1/customer/auth/*` and `/api/v1/customer/registration/*`.",
    "Implement separate registration (onboarding) and full-login services with separate token storage.",
    "Store access and refresh tokens in secure storage; implement single-flight refresh with rotation.",
    "Route every screen decision on `next_action`.",
    "Never send onboarding tokens to full Customer APIs.",
    "Map registration to profile + submit; collect `merchant_code`.",
    "Handle errors by `detail.code`; map `fields[]` to inline field errors; honour Retry-After.",
    "Do not enable a real KYC approval journey before document upload exists.",
    "Run Customer integration tests against the restarted backend.",
)
h2("20.2 Merchant App Team")
bullets(
    "Replace mock calls with `/api/v1/merchant/auth/*`.",
    "Store access and refresh tokens securely; restore sessions with `GET /api/v1/merchant/auth/me`.",
    "Route using `next_action`, `role` and `effective_permissions` (after the permission mapping is agreed).",
    "Implement single-flight refresh with rotation.",
    "Handle blocked, pending and rejected states (ACCOUNT_BLOCKED, MERCHANT_BLOCKED, ACCOUNT_PENDING_APPROVAL, ACCOUNT_REJECTED).",
    "Integrate `/api/v1/merchant/customers/*` only after reviewer permissions are assigned.",
    "Handle errors by code, including the list-format validation errors on review routes (CD-06).",
    "Run Merchant integration tests against the restarted backend.",
)
h2("20.3 Shared")
bullets(
    "Create an API adapter/normalizer if the existing camelCase TypeScript types must stay unchanged.",
    "Add the Authorization header automatically for Bearer routes only.",
    "Add single-flight refresh and prevent infinite refresh loops (refresh at most once per failed request).",
    "Clear secure tokens after revocation or logout.",
    "Log `X-Request-ID` for debugging; never log tokens, codes or full numbers.",
    "Update frontend tests and mocks to the new contracts.",
    "Run end-to-end tests after the backend restart.",
)

# ---------------------------------------------------------------------------------------------
h1("21. Required project decisions")
p("These decisions belong to the Product Owner. The backend team has not made them.")
numbers(
    "Which Merchant roles receive `customers.view`, `customers.approve` and `customers.reject`?",
    "Is Customer suspension and reinstatement in scope for this phase?",
    "Should blocked or unapproved users receive an explanatory SMS instead of no code?",
    "Which SMS vendor will be used?",
    "Which storage provider will hold Customer KYC files?",
    "May the frontend service contracts switch to backend snake_case, or should an adapter preserve the existing TypeScript interfaces?",
    "Which registration fields from the frontend form (owner name, email, address, industrial sites) must the backend store in this phase?",
    "How do frontend role and permission names map to backend codes (for example GODOWN_INCHARGE)?",
)

# ---------------------------------------------------------------------------------------------
h1("22. Definition of ready")
table(["Customer authentication ready for staging when", "Merchant authentication ready for staging when"], [
    ["Real SMS delivery works", "Real SMS delivery works"],
    ["Document upload is implemented", "Reviewer permissions are assigned (where Customer review is enabled)"],
    ["Reviewer permissions are assigned", "Merchant mobile integration tests pass"],
    ["Registration → approval → sign-in works with uploaded documents", "End-to-end tests pass"],
    ["Customer mobile integration tests pass", ""],
    ["End-to-end tests pass", ""],
], [8.6, 8.6])

# ---------------------------------------------------------------------------------------------
h1("23. Closing")
h2("23.1 Mobile integration start checklist")
bullets(
    "Backend server restarted and reachable at the agreed local or test base URL.",
    "Development OTP code obtained privately from the Backend Team (never committed or shared in chat).",
    "Test Merchant and Customer accounts provided by the Backend Team.",
    "Service-layer mapping and normalizer in place.",
    "Secure token storage and single-flight refresh implemented.",
    "Error handling by code, including Retry-After.",
)
h2("23.2 Pending decisions")
p("See section 21 (eight decisions).")
h2("23.3 Questions for the Backend Team")
bullets(
    "Which base URL and test accounts should each app team use?",
    "When will the stale 404 on `otp/request` be removed from OpenAPI (CD-01)?",
    "When will review routes return the coded validation envelope (CD-06)?",
    "Is a Customer registration detail endpoint (address, documents) planned, and when?",
    "What is the planned timeline for document upload and SMS vendor integration?",
)
h2("23.4 Final readiness verdict")
callout("info", "AUTHENTICATION APIS READY FOR MOBILE INTEGRATION WITH DOCUMENTED LIMITATIONS")
bullets(
    "Mobile integration may begin now.",
    "Staging or production sign-in cannot be completed until a real SMS vendor is integrated.",
    "Real Customer approval must not be enabled until KYC document upload and reviewer permissions are ready.",
)

BLOCKS = B
