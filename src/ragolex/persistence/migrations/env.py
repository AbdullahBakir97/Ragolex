"""Alembic environment: runs migrations with the app's async engine."""

import asyncio
import logging

from alembic import context
from sqlalchemy.engine import Connection

from ragolex.core.config import get_settings
from ragolex.core.logging_config import configure_logging
from ragolex.persistence.database import create_engine
from ragolex.persistence.tables import Base

config = context.config
target_metadata = Base.metadata

# Programmatic callers (e.g. the tests) keep their own logging setup. The
# CLI uses the app's log format and reports each migration it runs.
if config.attributes.get("configure_logging", True):
    configure_logging("WARNING")
    logging.getLogger("alembic").setLevel(logging.INFO)


def database_url() -> str:
    # A URL passed by programmatic callers (such as the tests) wins over the
    # application settings.
    return config.attributes.get("database_url") or get_settings().DATABASE_URL


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade --sql)."""
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
