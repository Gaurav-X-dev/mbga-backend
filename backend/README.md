# MBGA Backend

FastAPI backend scaffold for the MBGA Order Management and Payment Reconciliation System.

## Local Windows Setup

Docker is optional. The current local flow uses Python, PowerShell, locally installed MySQL 8+, and Redis later when OTP work begins.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
python scripts/check_setup.py
```

Edit `.env` with local MySQL credentials:

```env
DATABASE_URL=mysql+asyncmy://mbga_user:CHANGE_ME@127.0.0.1:3306/mbga?charset=utf8mb4
TEST_DATABASE_URL=mysql+asyncmy://mbga_test_user:CHANGE_ME@127.0.0.1:3306/mbga_test?charset=utf8mb4
```

After MySQL is running and the `mbga` database exists:

```powershell
alembic upgrade head
python scripts/seed_rbac.py
pytest -m unit -v
python scripts/check_setup.py --all
uvicorn app.main:app --reload
```

Local API: `http://localhost:8000`

Swagger docs: `http://localhost:8000/docs`

## MySQL

Use MySQL 8 with InnoDB and `utf8mb4_unicode_ci`.

UUIDs are stored as readable `String(36)` values. Application timestamps are UTC; do not rely on MySQL session timezone conversion for business logic.

Migration commands require a running local MySQL service:

```powershell
alembic heads
alembic upgrade head
alembic check
```

## Seed RBAC Data

```powershell
python scripts/seed_rbac.py
python scripts/seed_rbac.py
```

The second run should create no duplicates.

## Tests

```powershell
pytest -m unit -v
pytest -m "integration and mysql" -v
pytest -v
```

Integration tests require `TEST_DATABASE_URL` pointing to a disposable MySQL database whose name contains `test`, such as `mbga_test`. They must not run against `mbga`.

## Setup Helpers

```powershell
python scripts/check_setup.py
python scripts/check_setup.py --database
python scripts/check_setup.py --tests
python scripts/check_setup.py --all
python scripts/project_status.py
python scripts/setup_local.py
```

`scripts/setup_local.py` asks for confirmation before migrations and seeds.

## Super Admin Bootstrap

Super Admin bootstrap is disabled by default. Configure explicit environment variables first:

```text
RBAC_BOOTSTRAP_SUPER_ADMIN_ENABLED=true
RBAC_BOOTSTRAP_SUPER_ADMIN_USER_ID=<existing-user-id>
```

Then run:

```powershell
python scripts/bootstrap_super_admin.py
```

No user is created automatically and no real credential belongs in source code.

## Customer Approval Rule

Customer OTP verification alone does not grant full login. Customer details and mandatory documents must be completed, authorized Merchant approval is required, and only an approved, active, non-blocked Customer receives full Customer App tokens. Customer onboarding is implemented after the MySQL/RBAC foundation is verified.

## Optional Docker Setup

Docker files remain available for future use:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Docker is not required for initial local development.

## Current Scope

Login, OTP, JWT issuance, and frontend work are intentionally postponed until product-approved flows are provided. Current work covers the FastAPI scaffold, MySQL-ready migrations, dynamic RBAC APIs, explicit Super Admin permissions, audit-log reads, seed preparation, and setup verification tooling.

Admin RBAC APIs are mounted under `/api/v1/admin`, but they fail closed with `401` until verified authentication/current-user extraction is implemented. There are no `/api/v1/admin/auth/*` routes in this phase.
