import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from ragolex.persistence.database import create_engine
from ragolex.persistence.tables import Base

from .conftest import alembic_config

# Synchronous tests: Alembic's env.py runs its own event loop, like the CLI.
APP_TABLES = {"projects", "files", "chunks", "answers", "conversations", "conversation_messages"}


def run_on_connection(url, function):
    async def run():
        engine = create_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(function)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def table_names(connection):
    return set(inspect(connection).get_table_names())


def test_downgrade_and_upgrade_round_trip(migrated_database):
    config = alembic_config(migrated_database)
    try:
        command.downgrade(config, "base")
        tables_after_downgrade = run_on_connection(migrated_database, table_names)
        assert APP_TABLES.isdisjoint(tables_after_downgrade)
    finally:
        command.upgrade(config, "head")

    assert APP_TABLES <= run_on_connection(migrated_database, table_names)


def test_projects_from_before_tenants_go_to_the_default_tenant(db):
    config = alembic_config(db)

    def execute(sql):
        def run(connection):
            rows = connection.execute(text(sql))
            connection.commit()
            return rows.all() if rows.returns_rows else None
        return run_on_connection(db, run)

    try:
        command.downgrade(config, "0009")
        execute("INSERT INTO projects (name) VALUES ('legacy')")
        command.upgrade(config, "head")

        assert execute("SELECT t.name, p.name, p.storage_name FROM projects p "
                       "JOIN tenants t ON t.id = p.tenant_id") == [("default", "legacy", "legacy")]
    finally:
        command.upgrade(config, "head")


def test_models_and_migrations_are_in_sync(migrated_database):
    def schema_differences(connection):
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    assert run_on_connection(migrated_database, schema_differences) == []


def test_chunk_embeddings_have_a_cosine_hnsw_index(migrated_database):
    def embedding_index(connection):
        return connection.exec_driver_sql(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding'").scalar_one()

    definition = run_on_connection(migrated_database, embedding_index)

    assert "USING hnsw (embedding vector_cosine_ops)" in definition
