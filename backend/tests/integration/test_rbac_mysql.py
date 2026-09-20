import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.roles.seed_runner import RBACSeedRunner


pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def _env_file_value(name: str) -> str | None:
    path = Path(".env")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def _test_database_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL") or _env_file_value("TEST_DATABASE_URL")


def _is_disposable_mysql_test_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.startswith("mysql+asyncmy://") and "test" in lowered


@pytest.fixture(autouse=True)
def require_safe_test_database_url() -> None:
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is absent; MySQL integration tests skipped")
    if not url.lower().startswith("mysql+asyncmy://"):
        pytest.fail("TEST_DATABASE_URL must use mysql+asyncmy")
    if not _is_disposable_mysql_test_url(url):
        pytest.fail("TEST_DATABASE_URL must point to a disposable database whose name contains 'test'")


def _alembic_config() -> Config:
    url = _test_database_url() or ""
    os.environ["DATABASE_URL"] = url
    cfg = Config(str(Path("alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_mysql_migration_upgrade_creates_expected_tables() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    async def inspect_tables() -> set[str]:
        engine = create_async_engine(_test_database_url() or "")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        await engine.dispose()
        return tables

    import asyncio

    tables = asyncio.run(inspect_tables())
    assert {
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "role_login_channels",
        "user_roles",
        "audit_logs",
        "login_sessions",
    } <= tables


def test_seed_runner_is_idempotent_against_mysql() -> None:
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    async def run_seed_twice():
        engine = create_async_engine(_test_database_url() or "")
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            first_result = await RBACSeedRunner(session).run()
        async with session_factory() as session:
            second_result = await RBACSeedRunner(session).run()
        await engine.dispose()
        return first_result, second_result

    import asyncio

    first, second = asyncio.run(run_seed_twice())

    assert first["roles_created"] >= 8
    assert first["permissions_created"] >= 1
    assert second == {
        "roles_created": 0,
        "permissions_created": 0,
        "channels_created": 0,
        "super_admin_permissions_created": 0,
        "manager_permissions_created": 0,
        "delivery_role_permissions_created": 0,
    }


def test_mysql_migration_downgrade_only_on_disposable_database() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
