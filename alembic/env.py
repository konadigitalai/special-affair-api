"""Alembic environment.

Migration rule: expand/contract only. Never rename or drop a column in a single
migration; add nullable, backfill, dual-write, switch reads, then drop in a later
release. Use CREATE INDEX CONCURRENTLY for indexes on large tables.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.modules.content import models as content_models  # noqa: F401
from app.ai.shopping_copilot import models as copilot_models  # noqa: F401
from app.modules.cart import models as cart_models  # noqa: F401
from app.modules.checkout import models as checkout_models  # noqa: F401
from app.modules.orders import models as order_models  # noqa: F401
from app.modules.payments import models as payment_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    database = get_settings().migration_database
    context.configure(
        url=database.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    database = get_settings().migration_database
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database.url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=database.connect_args,
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
