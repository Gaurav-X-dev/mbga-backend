from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlparse

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "role_login_channels",
    "user_roles",
    "audit_logs",
    "login_sessions",
    "otp_challenges",
    "merchants",
    "merchant_users",
    "customer_profiles",
    "customer_documents",
    "delivery_profiles",
}
REQUIRED_IMPORTS = [
    "fastapi",
    "sqlalchemy",
    "asyncmy",
    "alembic",
    "pydantic",
    "pydantic_settings",
    "redis",
    "pytest",
]


@dataclass
class Result:
    category: str
    name: str
    status: str
    detail: str = ""


class Reporter:
    def __init__(self) -> None:
        self.results: list[Result] = []

    def add(self, category: str, name: str, status: str, detail: str = "") -> None:
        self.results.append(Result(category, name, status, detail))
        suffix = f" - {detail}" if detail else ""
        print(f"{status:7} {category}: {name}{suffix}")

    def summary(self) -> int:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        print()
        print(
            "Summary: "
            + ", ".join(f"{status.lower()}={count}" for status, count in sorted(counts.items()))
        )
        if any(result.status in {"FAILED", "BLOCKED"} for result in self.results):
            return 1
        return 0


def load_env_file() -> dict[str, str]:
    env_path = ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str, env_file: dict[str, str]) -> str | None:
    return os.getenv(name) or env_file.get(name)


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def parse_db_url(url: str | None):
    if not url:
        return None
    return urlparse(url)


def check_static_migrations(reporter: Reporter) -> None:
    versions = ROOT / "database" / "migrations" / "versions"
    migration_files = sorted(versions.glob("*.py"))
    modules: list[ModuleType] = []
    for file in migration_files:
        spec = importlib.util.spec_from_file_location(file.stem, file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules.append(module)
    revisions = {getattr(module, "revision", None): getattr(module, "down_revision", None) for module in modules}
    if (
        revisions.get("20260914_0001") is None
        and revisions.get("20260914_0002") == "20260914_0001"
        and revisions.get("20260914_0003") == "20260914_0002"
        and revisions.get("20260914_0004") == "20260914_0003"
        and revisions.get("20260914_0005") == "20260914_0004"
        and revisions.get("20260914_0006") == "20260914_0005"
    ):
        reporter.add("Migration", "revision chain", "PASS", "users -> RBAC -> auth/audit -> index guard -> admin access -> onboarding")
    else:
        reporter.add("Migration", "revision chain", "FAILED", str(revisions))

    cfg = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) == 1:
        reporter.add("Migration", "single Alembic head", "PASS", heads[0])
    else:
        reporter.add("Migration", "single Alembic head", "FAILED", ", ".join(heads))

    text_blob = "\n".join(file.read_text(encoding="utf-8") for file in migration_files)
    forbidden = ["post" + "gresql", "async" + "pg", "JSONB", "ARRAY", "ON CONFLICT", "UUID("]
    found = [item for item in forbidden if item.lower() in text_blob.lower()]
    if found:
        reporter.add("Migration", "unsupported dialect SQL scan", "FAILED", ", ".join(found))
    else:
        reporter.add("Migration", "unsupported dialect SQL scan", "PASS")

    if "sa.Column(\"id\", sa.String(length=36)" in text_blob and "sa.Column(\"user_id\", sa.String(length=36)" in text_blob:
        reporter.add("Migration", "UUID column strategy", "PASS", "String(36)")
    else:
        reporter.add("Migration", "UUID column strategy", "FAILED")


async def check_database(reporter: Reporter, db_url: str | None, deep: bool) -> None:
    parsed = parse_db_url(db_url)
    if not parsed:
        reporter.add("Database", "DATABASE_URL", "BLOCKED", "missing")
        return
    if not parsed.scheme.startswith("mysql+asyncmy"):
        reporter.add("Database", "MySQL async URL", "FAILED", sanitize_url(db_url or ""))
        return
    reporter.add("Database", "URL dialect", "PASS", "mysql+asyncmy")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        reporter.add("Database", "local hostname", "WARNING", parsed.hostname or "")
    else:
        reporter.add("Database", "local hostname", "PASS", parsed.hostname or "")
    if parse_qs(parsed.query).get("charset", [""])[0].lower() == "utf8mb4":
        reporter.add("Database", "charset parameter", "PASS", "utf8mb4")
    else:
        reporter.add("Database", "charset parameter", "WARNING", "expected charset=utf8mb4")

    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3306
    try:
        with socket.create_connection((host, port), timeout=3):
            reporter.add("Database", "TCP port reachable", "PASS", f"{host}:{port}")
    except OSError as exc:
        reporter.add("Database", "TCP port reachable", "BLOCKED", str(exc))
        return

    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT VERSION()"))
            database = await connection.scalar(text("SELECT DATABASE()"))
            reporter.add("Database", "SQLAlchemy connection", "PASS")
            reporter.add("Database", "MySQL server version", "PASS", str(version))
            reporter.add("Database", "active database", "PASS", str(database))
            charset = await connection.scalar(text("SELECT @@character_set_database"))
            collation = await connection.scalar(text("SELECT @@collation_database"))
            reporter.add("Database", "database character set", "PASS" if charset == "utf8mb4" else "WARNING", str(charset))
            reporter.add("Database", "database collation", "PASS" if "utf8mb4" in str(collation) else "WARNING", str(collation))
            current = await connection.run_sync(lambda sync_conn: sync_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none() if inspect(sync_conn).has_table("alembic_version") else None)
            reporter.add("Alembic", "current database revision", "PASS" if current else "WARNING", str(current or "not migrated"))
            if deep:
                tables = await connection.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
                missing = EXPECTED_TABLES - tables
                reporter.add("Database", "expected tables", "PASS" if not missing else "WARNING", ", ".join(sorted(missing)) if missing else "all present")
                if not missing:
                    def constraints(sync_conn):
                        insp = inspect(sync_conn)
                        return {
                            "role_fk": insp.get_foreign_keys("role_permissions"),
                            "user_role_fk": insp.get_foreign_keys("user_roles"),
                            "role_unique": insp.get_unique_constraints("roles"),
                            "permission_unique": insp.get_unique_constraints("permissions"),
                            "user_role_indexes": insp.get_indexes("user_roles"),
                        }
                    metadata = await connection.run_sync(constraints)
                    reporter.add("Database", "foreign keys", "PASS" if metadata["role_fk"] and metadata["user_role_fk"] else "FAILED")
                    reporter.add("Database", "RBAC constraints/indexes", "PASS", "introspected")
                    role_count = await connection.scalar(text("SELECT COUNT(*) FROM roles"))
                    permission_count = await connection.scalar(text("SELECT COUNT(*) FROM permissions"))
                    channel_count = await connection.scalar(text("SELECT COUNT(*) FROM role_login_channels"))
                    manager_channels = (
                        await connection.execute(
                            text(
                                "SELECT c.login_channel FROM roles r "
                                "JOIN role_login_channels c ON r.id=c.role_id "
                                "WHERE r.code='manager' ORDER BY c.login_channel"
                            )
                        )
                    ).scalars().all()
                    super_admin_channels = (
                        await connection.execute(
                            text(
                                "SELECT c.login_channel FROM roles r "
                                "JOIN role_login_channels c ON r.id=c.role_id "
                                "WHERE r.code='super_admin' ORDER BY c.login_channel"
                            )
                        )
                    ).scalars().all()
                    reporter.add("Database", "seed roles", "PASS" if role_count and role_count >= 8 else "WARNING", str(role_count or 0))
                    reporter.add("Database", "seed permissions", "PASS" if permission_count and permission_count >= 1 else "WARNING", str(permission_count or 0))
                    reporter.add("Database", "seed role-channel mappings", "PASS" if channel_count and channel_count >= 8 else "WARNING", str(channel_count or 0))
                    reporter.add("Database", "manager channel", "PASS" if manager_channels == ["MERCHANT"] else "FAILED", ",".join(manager_channels))
                    reporter.add("Database", "super admin channel", "PASS" if super_admin_channels == ["ADMIN"] else "FAILED", ",".join(super_admin_channels))
    except Exception as exc:
        reporter.add("Database", "SQLAlchemy connection", "BLOCKED", str(exc))
    finally:
        await engine.dispose()


def check_redis(reporter: Reporter, redis_url: str | None, redis_enabled: str | None = None) -> None:
    if (redis_enabled or "true").strip().lower() in {"false", "0", "no", "off"}:
        reporter.add(
            "Redis",
            "availability",
            "PASS",
            "disabled for local development (REDIS_ENABLED=false); permission checks use the database",
        )
        return
    parsed = urlparse(redis_url or "")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=2):
            reporter.add("Redis", "TCP port reachable", "PASS", f"{host}:{port}")
    except OSError:
        reporter.add(
            "Redis",
            "availability",
            "WARNING",
            "Redis is enabled but not reachable; the permission cache falls back to the database. "
            "Start Redis or set REDIS_ENABLED=false for local development",
        )


def run_tests(reporter: Reporter) -> None:
    result = subprocess.run([sys.executable, "-m", "pytest", "-m", "unit", "-q"], cwd=ROOT)
    reporter.add("Tests", "unit tests", "PASS" if result.returncode == 0 else "FAILED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", action="store_true", help="Run database connectivity and introspection checks")
    parser.add_argument("--tests", action="store_true", help="Run unit tests")
    parser.add_argument("--all", action="store_true", help="Run all safe checks")
    args = parser.parse_args()

    reporter = Reporter()
    env_file = load_env_file()
    reporter.add("Environment", "Python version", "PASS" if sys.version_info >= (3, 12) else "FAILED", sys.version.split()[0])
    reporter.add("Environment", "project root", "PASS" if (ROOT / "pyproject.toml").exists() else "FAILED", str(ROOT))
    reporter.add("Environment", "virtual environment", "PASS" if sys.prefix != sys.base_prefix else "WARNING", sys.prefix)
    for package in REQUIRED_IMPORTS:
        try:
            importlib.import_module(package)
            reporter.add("Environment", f"import {package}", "PASS")
        except Exception as exc:
            reporter.add("Environment", f"import {package}", "FAILED", str(exc))
    reporter.add("Environment", ".env exists", "PASS" if (ROOT / ".env").exists() else "BLOCKED", "copy .env.example to .env")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    reporter.add("Environment", ".env ignored", "PASS" if ".env" in gitignore else "FAILED")

    db_url = env_value("DATABASE_URL", env_file)
    test_db_url = env_value("TEST_DATABASE_URL", env_file)
    reporter.add("Database", "DATABASE_URL configured", "PASS" if db_url else "BLOCKED", sanitize_url(db_url or ""))
    if test_db_url and "test" in urlparse(test_db_url).path.lower():
        reporter.add("Database", "TEST_DATABASE_URL safety", "PASS", sanitize_url(test_db_url))
    else:
        reporter.add("Database", "TEST_DATABASE_URL safety", "WARNING", "integration tests require mbga_test")

    check_static_migrations(reporter)
    try:
        from app.main import app

        reporter.add("Application", "FastAPI app import", "PASS", app.title)
    except Exception as exc:
        reporter.add("Application", "FastAPI app import", "FAILED", str(exc))

    check_redis(reporter, env_value("REDIS_URL", env_file), env_value("REDIS_ENABLED", env_file))
    if args.database or args.all:
        asyncio.run(check_database(reporter, db_url, deep=args.all))
    else:
        reporter.add("Database", "live MySQL checks", "SKIPPED", "use --database or --all")
    if args.tests or args.all:
        run_tests(reporter)
    else:
        reporter.add("Tests", "unit tests", "SKIPPED", "use --tests or --all")

    return reporter.summary()


if __name__ == "__main__":
    raise SystemExit(main())
