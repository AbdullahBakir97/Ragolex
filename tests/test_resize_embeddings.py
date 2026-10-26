"""Switching the stored vector size, for an embedding model with vectors of another length."""

import asyncio

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import make_url
from sqlalchemy import text as sql_text

from ragolex.cli import main
from ragolex.core.config import get_settings
from ragolex.persistence.database import (
    create_engine,
    resize_embeddings,
    stored_embedding_dimensions,
)

from .conftest import TEST_DATABASE_URL, _ensure_database, alembic_config

# Resizing changes the schema, so these tests use a database of their own.
_url = make_url(TEST_DATABASE_URL)
RESIZE_DATABASE_URL = _url.set(database=f"{_url.database}_resize").render_as_string(
    hide_password=False)


async def _run(sql: str, params: dict | None = None):
    engine = create_engine(RESIZE_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(sql_text(sql), params or {})
            return result.all() if result.returns_rows else None
    finally:
        await engine.dispose()


def run(sql: str, params: dict | None = None):
    return asyncio.run(_run(sql, params))


async def _stored_dimensions() -> int | None:
    engine = create_engine(RESIZE_DATABASE_URL)
    try:
        return await stored_embedding_dimensions(engine)
    finally:
        await engine.dispose()


def stored_dimensions() -> int | None:
    return asyncio.run(_stored_dimensions())


async def _resize(dimensions: int) -> int:
    engine = create_engine(RESIZE_DATABASE_URL)
    try:
        return await resize_embeddings(engine, dimensions)
    finally:
        await engine.dispose()


def add_chunk(vector: list[float] | None):
    run("INSERT INTO tenants (name) VALUES ('default') ON CONFLICT DO NOTHING")
    run("INSERT INTO projects (tenant_id, name, storage_name) "
        "SELECT id, 'demo', 'demo' FROM tenants WHERE name = 'default' ON CONFLICT DO NOTHING")
    run("INSERT INTO files (project_id, key, original_name, content_type, size_bytes) "
        "SELECT id, 'abc_notes.txt', 'notes.txt', 'text/plain', 1 FROM projects "
        "ON CONFLICT DO NOTHING")
    run("INSERT INTO chunks (file_id, project_id, chunk_index, text, metadata, embedding) "
        "SELECT f.id, f.project_id, coalesce(max(c.chunk_index) + 1, 0), 'text', '{}', "
        "CAST(:vector AS vector) FROM files f LEFT JOIN chunks c ON c.file_id = f.id "
        "GROUP BY f.id, f.project_id",
        {"vector": None if vector is None else str(vector)})


@pytest.fixture
def resize_db(monkeypatch):
    asyncio.run(_ensure_database(RESIZE_DATABASE_URL))
    command.upgrade(alembic_config(RESIZE_DATABASE_URL), "head")
    monkeypatch.setenv("DATABASE_URL", RESIZE_DATABASE_URL)
    get_settings.cache_clear()
    yield RESIZE_DATABASE_URL
    run("TRUNCATE tenants, projects, files, chunks, answers, conversations, conversation_messages "
        "RESTART IDENTITY CASCADE")
    if stored_dimensions() != 1536:
        asyncio.run(_resize(1536))


def test_resizing_clears_the_vectors_and_keeps_the_chunks(resize_db):
    add_chunk([0.5] * 1536)
    add_chunk(None)

    cleared = asyncio.run(_resize(768))

    assert cleared == 1
    assert stored_dimensions() == 768
    assert run("SELECT count(*), count(embedding) FROM chunks") == [(2, 0)]
    [(index,)] = run("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding'")
    assert "hnsw" in index and "vector_cosine_ops" in index
    add_chunk([0.5] * 768)  # vectors of the new length fit


@pytest.mark.parametrize("dimensions", [0, 2001])
def test_sizes_the_index_cannot_hold_are_refused(dimensions):
    with pytest.raises(ValueError, match="1-2000"):
        asyncio.run(resize_embeddings(None, dimensions))


def test_the_app_resizes_an_empty_column_at_start(resize_db, monkeypatch):
    from ragolex.main import create_app

    add_chunk(None)  # chunks without vectors lose nothing
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert stored_dimensions() == 768


def test_the_app_refuses_to_start_when_stored_vectors_do_not_fit(resize_db, monkeypatch):
    from ragolex.main import create_app

    add_chunk([0.5] * 1536)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match=r"768.*1 vectors of 1536.*ragolex resize-embeddings"):
        with TestClient(create_app()):
            pass
    assert stored_dimensions() == 1536


def test_the_command_resizes_once(resize_db, monkeypatch, capsys):
    add_chunk([0.5] * 1536)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    get_settings.cache_clear()

    assert main(["resize-embeddings"]) == 0
    assert "768 dimensions instead of 1536. 1 stored vectors were cleared" in capsys.readouterr().out
    assert main(["resize-embeddings"]) == 0
    assert "already have 768 dimensions" in capsys.readouterr().out
    assert stored_dimensions() == 768


def test_the_command_reports_an_unreachable_database(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    get_settings.cache_clear()

    assert main(["resize-embeddings"]) == 1
    assert "unreachable or not migrated" in capsys.readouterr().err
