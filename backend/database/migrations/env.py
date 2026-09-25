from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config.app import get_settings

# Import models so Alembic sees the approved metadata.
from app.modules.audit_logs import models as audit_log_models  # noqa: F401
from app.modules.authentication import models as authentication_models  # noqa: F401
from app.modules.authentication import otp_models as otp_models  # noqa: F401
from app.modules.constants import models as constant_models  # noqa: F401
from app.modules.customers import models as customer_models  # noqa: F401
from app.modules.deliveries import models as delivery_slip_models  # noqa: F401
from app.modules.delivery_users import models as delivery_user_models  # noqa: F401
from app.modules.expenses import models as expense_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.merchants import models as merchant_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.orders import models as order_models  # noqa: F401
from app.modules.permissions import models as permission_models  # noqa: F401
from app.modules.pricing import models as pricing_models  # noqa: F401
from app.modules.roles import models as role_models  # noqa: F401
from app.modules.tasks import models as task_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401
from app.modules.users import role_models as user_role_models  # noqa: F401
from app.shared.database.base import Base
from app.shared.idempotency import models as idempotency_models  # noqa: F401
from app.shared.notifications import models as notification_outbox_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which switches off every logger that was
    # already created - including the application's. In-process migrations (the test suite,
    # any management command) would then silently drop all application logging afterwards.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
