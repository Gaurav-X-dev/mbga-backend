# Local MySQL Setup For Windows

This project uses MySQL 8+ for local development. Docker is optional.

## 1. Install MySQL

Install MySQL Community Server 8+ from the official MySQL installer. During installation, remember the local root password you choose.

## 2. Start The MySQL Service

Open Windows Services and confirm the MySQL service is running. It is commonly named `MySQL80` or similar.

PowerShell check:

```powershell
Get-Service *mysql*
```

## 3. Connect To MySQL

Use MySQL Command Line Client or MySQL Workbench.

## 4. Create Databases

Use placeholders. Do not paste real passwords into source files.

```sql
CREATE DATABASE mbga
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE DATABASE mbga_test
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

`mbga` is the local development database. `mbga_test` is disposable and may be modified by integration tests.

## 5. Create Local Users

```sql
CREATE USER 'mbga_user'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER 'mbga_test_user'@'localhost' IDENTIFIED BY 'CHANGE_ME';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON mbga.* TO 'mbga_user'@'localhost';

GRANT ALL PRIVILEGES
  ON mbga_test.* TO 'mbga_test_user'@'localhost';

FLUSH PRIVILEGES;
```

You may also grant for `127.0.0.1` depending on your MySQL authentication setup:

```sql
CREATE USER 'mbga_user'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME';
CREATE USER 'mbga_test_user'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME';
```

## 6. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Then edit:

```env
DATABASE_URL=mysql+asyncmy://mbga_user:CHANGE_ME@127.0.0.1:3306/mbga?charset=utf8mb4
TEST_DATABASE_URL=mysql+asyncmy://mbga_test_user:CHANGE_ME@127.0.0.1:3306/mbga_test?charset=utf8mb4
REDIS_URL=redis://127.0.0.1:6379/0
```

Do not commit `.env`.

## 7. Check Setup

```powershell
python scripts/check_setup.py
python scripts/check_setup.py --database
```

## 8. Run Migrations And Seed RBAC

```powershell
alembic upgrade head
python scripts/seed_rbac.py
python scripts/seed_rbac.py
```

The second seed run should create no duplicates.

## 9. Run Tests

```powershell
pytest -m unit -v
pytest -m "integration and mysql" -v
```

Integration tests must only use `mbga_test`.

## Troubleshooting

Port `3306`:

```powershell
Test-NetConnection 127.0.0.1 -Port 3306
```

Access denied:

- Verify username and password in `.env`.
- Check whether MySQL user is created for `localhost` or `127.0.0.1`.
- Re-run `FLUSH PRIVILEGES`.

Unknown database:

- Confirm `CREATE DATABASE mbga` and `CREATE DATABASE mbga_test` were executed.
- Check spelling in `DATABASE_URL`.

MySQL service issues:

- Open Windows Services and start MySQL.
- Check MySQL Workbench can connect.
- Restart the service after configuration changes.

## Safety

Never run destructive integration tests against `mbga`. The test database name must clearly contain `test`.
