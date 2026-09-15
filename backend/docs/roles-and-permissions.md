# Roles And Permissions

## Core Distinction

- Login channel: deployed application/API used for sign-in, for example `CUSTOMER`, `DELIVERY`, `MERCHANT`, `ADMIN`.
- Role: database record describing business access, for example Customer, Driver, Helper, Manager, Accountant, or a custom role.
- Permission: database record describing an exact action, for example `orders.view` or `roles.manage`.

Login channels may remain system constants. Roles and permissions are database-driven and are the authorization source of truth.

## Database Relationships

- `users` to `user_roles`: one user can have many role assignments.
- `roles` to `role_permissions`: one role can grant many permissions.
- `permissions`: exact action records using `module.action` codes.
- `roles` to `role_login_channels`: a role can be allowed or blocked per login channel.

Effective permissions are calculated through:

```text
Active User -> active/current UserRole -> active Role -> allowed Login Channel -> active RolePermission -> active Permission
```

The calculation also checks user status, role assignment validity dates, and role-login-channel mappings.

## Permission Naming

Permission codes use:

```text
module.action
```

Examples:

```text
orders.view
payments.reconcile
inventory.adjust
roles.assign_permissions
users.assign_roles
```

## Cache Behavior

Effective permissions can be cached in Redis with:

```text
auth:permissions:user:{user_id}:v{permission_version}
```

Redis failure must fail safely. A cache read failure falls back to the database. Authorization must never grant access from missing or unverifiable data.

Invalidate permission cache when:

- A role is assigned or removed.
- A role is activated or deactivated.
- A permission is added to or removed from a role.
- A permission is activated or deactivated.
- Role-channel access changes.

## Admin APIs

Prepared under `/api/v1/admin`:

- `POST /roles`
- `GET /roles`
- `GET /roles/{role_id}`
- `PATCH /roles/{role_id}`
- `DELETE /roles/{role_id}`
- `POST /roles/{role_id}/activate`
- `POST /roles/{role_id}/deactivate`
- `GET /roles/{role_id}/permissions`
- `PUT /roles/{role_id}/permissions`
- `POST /roles/{role_id}/permissions/{permission_id}`
- `DELETE /roles/{role_id}/permissions/{permission_id}`
- `GET /roles/{role_id}/channels`
- `PUT /roles/{role_id}/channels`
- `GET /roles/{role_id}/users`
- `GET /permissions`
- `GET /permissions/{permission_id}`
- `GET /permissions/grouped`
- `GET /users`
- `GET /users/{user_id}`
- `GET /users/{user_id}/roles`
- `POST /users/{user_id}/roles`
- `PATCH /users/{user_id}/roles/{assignment_id}`
- `DELETE /users/{user_id}/roles/{assignment_id}`
- `GET /users/{user_id}/effective-permissions`
- `GET /users/{user_id}/allowed-channels`
- `GET /audit-logs`
- `GET /audit-logs/{audit_log_id}`

These routes are wired with permission dependencies. Login/current-user extraction is intentionally postponed, so production runtime fails closed with `401 Authentication required`. Tests use FastAPI dependency overrides only inside test code.

No `/api/v1/admin/auth/*` routes are mounted in this phase.

## Super Admin Bootstrap

Super Admin must be created through an environment-controlled bootstrap script after explicit approval. No real mobile number, password, OTP, or secret should be committed.

Required variables:

```text
RBAC_BOOTSTRAP_SUPER_ADMIN_ENABLED=true
RBAC_BOOTSTRAP_SUPER_ADMIN_USER_ID=<existing-user-id>
```

or:

```text
RBAC_BOOTSTRAP_SUPER_ADMIN_MOBILE_NUMBER=<existing-mobile>
RBAC_BOOTSTRAP_SUPER_ADMIN_COUNTRY_CODE=+91
```

Run:

```bash
python scripts/bootstrap_super_admin.py
```

The bootstrap is idempotent, refuses ambiguous mobile-number matches, assigns the existing user to the explicit `super_admin` database role, and writes an audit log. It does not create a password or finalize login credentials.

## Running Migrations And Seeds

```bash
alembic check
alembic upgrade head
python scripts/seed_rbac.py
```

The users baseline migration is `20260914_0001`, the RBAC migration is `20260914_0002`, and auth/audit scaffold alignment is `20260914_0003`.

Tables created:

- `roles`
- `permissions`
- `role_permissions`
- `role_login_channels`
- `user_roles`
- `audit_logs`
- `login_sessions`

Migration order is:

1. `20260914_0001_create_users_table`
2. `20260914_0002_create_rbac_tables`
3. `20260914_0003_create_auth_audit_scaffold_tables`
4. `20260914_0004_ensure_user_roles_validity_index`
5. `20260914_0005_admin_access_management_columns`

`user_roles.user_id` references `users.id`, and both use MySQL-compatible `String(36)` UUID storage.

## Testing

- Unit tests: `pytest tests/unit -v`
- API tests: `pytest tests/api -v`
- MySQL integration tests: set `TEST_DATABASE_URL` to a disposable MySQL database, then run `pytest tests/integration -v`

Never use SQLite as proof of MySQL migration compatibility.

## MySQL Compatibility

- Driver: `asyncmy`
- URL format: `mysql+asyncmy://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4`
- Storage engine: InnoDB
- Charset/collation: `utf8mb4` / `utf8mb4_unicode_ci`
- UUID strategy: readable `CHAR/VARCHAR(36)` string values in application-generated UUID format
- Timestamp strategy: application stores UTC datetime values; MySQL timezone-aware timestamp semantics are not relied on
- Duplicate user-role scope strategy: `scope_type` and `scope_id` default to `global` instead of nullable values, because MySQL unique constraints allow multiple `NULL` values

## Security Rules

- Do not trust role or permission values submitted by clients.
- Do not assign privileged roles during public OTP registration.
- Do not grant Admin-channel access based only on role name.
- Do not delete protected system roles through normal APIs.
- Do not remove the last active Super Admin.
- Do not create wildcard permissions until separately designed and tested.
- Do not expose development authentication bypasses.
- Do not accept user IDs, role codes, or permission codes from request headers as trusted identity.

## Current TODO

- Finalize product-approved login/current-user extraction for Admin, Merchant, Customer, Delivery Partner, Driver, and Helper.
- Complete deeper concurrent last-Super-Admin locking around all indirect bulk operations.
- Confirm exact MBGA business role-to-permission matrix before granting broad permissions.

## Customer Approval Rule

Customer OTP verification alone does not grant full Customer App access. Customer details and mandatory documents must be completed, authorized Merchant approval is required, and only an approved, active and non-blocked Customer receives full Customer App tokens.
