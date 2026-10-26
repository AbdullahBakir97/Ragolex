import anyio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ragolex.core.config import MAX_INDEXED_DIMENSIONS


def create_engine(url: str) -> AsyncEngine:
    # pool_pre_ping replaces connections the database has closed (e.g. after
    # a restart) instead of failing the next request.
    return create_async_engine(url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False keeps loaded objects usable after commit, which
    # async code needs because it cannot lazily reload attributes.
    return async_sessionmaker(engine, expire_on_commit=False)


async def is_database_available(engine: AsyncEngine, timeout_seconds: float = 3.0) -> bool:
    """Whether the database answers a trivial query within the timeout."""
    try:
        with anyio.fail_after(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def stored_embedding_dimensions(engine: AsyncEngine,
                                      timeout_seconds: float = 3.0) -> int | None:
    """Length of chunks.embedding in the database.

    None when it cannot be told: the database is unreachable or not
    migrated yet.
    """
    # For a vector column, the type modifier is its number of dimensions.
    query = text("SELECT atttypmod FROM pg_attribute "
                 "WHERE attrelid = to_regclass('chunks') AND attname = 'embedding' "
                 "AND NOT attisdropped")
    try:
        with anyio.fail_after(timeout_seconds):
            async with engine.connect() as connection:
                return await connection.scalar(query)
    except Exception:
        return None


async def count_embeddings(engine: AsyncEngine) -> int:
    """Chunks that have an embedding."""
    async with engine.connect() as connection:
        return await connection.scalar(
            text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"))


async def resize_embeddings(engine: AsyncEngine, dimensions: int) -> int:
    """Make chunks.embedding hold vectors of ``dimensions``; returns how many were cleared.

    Vectors of another length come from another model and cannot be compared
    with new ones, so all are cleared. The chunks stay; indexing embeds them
    again. Runs in one transaction, index included.
    """
    if not 0 < dimensions <= MAX_INDEXED_DIMENSIONS:
        raise ValueError(f"dimensions must be 1-{MAX_INDEXED_DIMENSIONS}, not {dimensions}")
    async with engine.begin() as connection:
        cleared = await connection.scalar(
            text("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"))
        await connection.execute(text("DROP INDEX IF EXISTS ix_chunks_embedding"))
        # The length is a validated int; DDL cannot take it as a parameter.
        await connection.execute(text(
            f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({dimensions}) USING NULL"))
        await connection.execute(text(
            "CREATE INDEX ix_chunks_embedding ON chunks "
            "USING hnsw (embedding vector_cosine_ops)"))
    return cleared


class EmbeddingDimensionsMismatch(RuntimeError):
    """Stored vectors have another length than the one configured."""


async def match_embedding_dimensions(engine: AsyncEngine, wanted: int) -> int | None:
    """Make chunks.embedding fit vectors of ``wanted`` dimensions.

    With no vectors stored yet, a column of another length is resized, since
    nothing is lost, and its old length is returned. With vectors stored,
    EmbeddingDimensionsMismatch names the command that resizes it. Returns
    None when nothing changed, including when the database cannot be asked.
    """
    stored = await stored_embedding_dimensions(engine)
    if stored is None or stored == wanted:
        return None
    embedded = await count_embeddings(engine)
    if embedded:
        raise EmbeddingDimensionsMismatch(
            f"EMBEDDING_DIMENSIONS is {wanted}, but the database stores {embedded} vectors of "
            f"{stored} dimensions. Set it back to {stored}, or switch to {wanted} with "
            f"`ragolex resize-embeddings` (with Docker: `docker compose run --rm app "
            f"ragolex resize-embeddings`), which clears the stored vectors so the projects "
            f"can be indexed again with the new model.")
    await resize_embeddings(engine, wanted)
    return stored
