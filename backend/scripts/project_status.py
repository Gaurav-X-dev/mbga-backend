from __future__ import annotations

import socket
import sys
import asyncio
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def can_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


async def _current_revision(db_url: str) -> str:
    try:
        engine = create_async_engine(db_url)
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='alembic_version'"
                )
            )
            if not exists:
                return "not migrated"
            return str(await connection.scalar(text("SELECT version_num FROM alembic_version")))
    except Exception:
        return "unavailable"
    finally:
        try:
            await engine.dispose()
        except Exception:
            pass


def current_revision(db_url: str) -> str:
    return asyncio.run(_current_revision(db_url))


def main() -> None:
    env = load_env()
    db_url = env.get("DATABASE_URL", "mysql+asyncmy://mbga_user:***@127.0.0.1:3306/mbga?charset=utf8mb4")
    parsed = urlparse(db_url)
    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    redis = urlparse(env.get("REDIS_URL", "redis://127.0.0.1:6379/0"))

    print("Application name: MBGA Backend")
    print(f"Application environment: {env.get('APP_ENV', 'development')}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"Database dialect: {parsed.scheme}")
    print(f"Database host: {parsed.hostname}:{parsed.port or 3306}")
    print(f"Database name: {parsed.path.lstrip('/')}")
    print(f"MySQL connectivity: {'reachable' if can_connect(parsed.hostname or '127.0.0.1', parsed.port or 3306) else 'blocked'}")
    print(f"Alembic head: {', '.join(heads)}")
    print(f"Current migration revision: {current_revision(db_url)}")
    print("Unit-test readiness: ready")
    test_url = env.get("TEST_DATABASE_URL", "")
    print(f"Integration-test readiness: {'ready' if 'test' in test_url.lower() else 'needs TEST_DATABASE_URL'}")
    print(f"Redis readiness: {'reachable' if can_connect(redis.hostname or '127.0.0.1', redis.port or 6379) else 'optional/not reachable'}")
    print("OTP implementation status: not implemented")
    print("RBAC implementation status: scaffolded with MySQL migrations and seed runner")
    print("Customer onboarding implementation status: pending after MySQL/RBAC verification")


if __name__ == "__main__":
    main()
