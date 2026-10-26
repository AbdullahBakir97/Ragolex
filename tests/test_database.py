import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ragolex.core.config import get_settings
from ragolex.persistence.database import (
    create_engine,
    create_session_factory,
    stored_embedding_dimensions,
)

pytestmark = pytest.mark.anyio


async def test_session_factory_connects_to_postgres(database_url):
    engine = create_engine(database_url)
    try:
        async with create_session_factory(engine)() as session:
            version = await session.scalar(text("SHOW server_version"))
    finally:
        await engine.dispose()

    assert int(version.split(".")[0]) >= 16


def test_app_lifespan_opens_and_closes_the_pool(client):
    engine = client.app.state.engine

    assert engine.url.render_as_string(hide_password=True).startswith("postgresql+asyncpg://")


def test_database_url_must_be_async_postgres(monkeypatch):
    from pydantic import ValidationError

    from ragolex.core.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:///db.sqlite")

    with pytest.raises(ValidationError):
        Settings()


def test_app_starts_without_a_database_to_check_dimensions_against(monkeypatch):
    from ragolex.main import create_app

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/none")

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").status_code == 503


def test_embedder_is_created_only_when_configured(db, monkeypatch):
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        assert client.app.state.embedder is not None

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.app.state.embedder is None


async def test_stored_embedding_dimensions(migrated_database):
    engine = create_engine(migrated_database)
    unreachable = create_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    try:
        assert await stored_embedding_dimensions(engine) == 1536
        assert await stored_embedding_dimensions(unreachable) is None
    finally:
        await engine.dispose()
        await unreachable.dispose()
