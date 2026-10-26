import asyncio
import io
import os
import zipfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import make_url
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import create_async_engine

from ragolex.api.dependencies import get_embedder, get_llm
from ragolex.core.config import get_settings
from ragolex.loaders.registry import default_loader_registry
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import unit_of_work_factory
from ragolex.services.job_runner import JobRunner
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeEmbedder, FakeLLM

ROOT = Path(__file__).resolve().parents[1]

# A disposable database: tests empty its tables. Defaults to one next to the
# compose.yaml database, created on first use; CI sets TEST_DATABASE_URL.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ragolex:ragolex@localhost:5432/ragolex_test",
)

TEST_ENV = {
    "APP_NAME": "Ragolex-test",
    "APP_VERSION": "0.0.1",
    "OPENAI_API_KEY": "test-key",
    "FILE_MAX_SIZE": "1",
    "FILE_DEFAULT_CHUNK_SIZE": "1024",
    "DATABASE_URL": TEST_DATABASE_URL,
    # Tests run jobs themselves (see test_jobs.py), so they never race a worker.
    "JOB_WORKERS": "0",
}


@pytest.fixture
def files_dir(tmp_path):
    """Temporary storage root for uploaded files."""
    return tmp_path / "files"


@pytest.fixture(autouse=True)
def settings_env(monkeypatch, files_dir):
    """Provide settings via env vars instead of a local .env file."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("FILES_DIR", str(files_dir))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _ensure_database(url: str) -> None:
    """Create the test database if the server does not have it yet."""
    target = make_url(url)
    # CREATE DATABASE cannot run in a transaction, hence AUTOCOMMIT.
    engine = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                sql_text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database})
            if not exists:
                await connection.execute(sql_text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url():
    """URL of a reachable test database; stops the run with a hint if there is none."""
    try:
        asyncio.run(_ensure_database(TEST_DATABASE_URL))
    except Exception as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at {TEST_DATABASE_URL} ({exc!r}).\n"
            "Start it with `docker compose up -d db`, or set TEST_DATABASE_URL.",
            returncode=1,
        )
    return TEST_DATABASE_URL


def alembic_config(url: str) -> Config:
    config = Config(toml_file=str(ROOT / "pyproject.toml"))
    config.attributes["database_url"] = url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def migrated_database(database_url):
    """The test database, migrated to the latest schema once per run."""
    command.upgrade(alembic_config(database_url), "head")
    return database_url


async def _empty_tables(url: str) -> None:
    engine = create_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(sql_text(
                "TRUNCATE projects, files, chunks, answers, conversations, conversation_messages, jobs, webhooks, webhook_deliveries, tenants, api_keys RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
def db(migrated_database):
    """A migrated database that is emptied after the test."""
    yield migrated_database
    asyncio.run(_empty_tables(migrated_database))


def build_pdf(pages: list[str]) -> bytes:
    """Build a minimal valid PDF with one page per string (lines split on \\n)."""
    def escape(line):
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        lines = " ".join(f"({escape(line)}) Tj T*" for line in text.split("\n") if line)
        stream = f"BT /F1 12 Tf 72 720 Td 14 TL {lines} ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_offset = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref_offset)
    return pdf


@pytest.fixture
def make_pdf():
    return build_pdf


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def build_docx(body: str, styles: str = "") -> bytes:
    """Build a minimal Word document from ``w:body`` XML (and ``w:styles`` XML)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'))
        archive.writestr("word/document.xml",
                         f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>')
        if styles:
            archive.writestr("word/styles.xml", f'<w:styles xmlns:w="{_W}">{styles}</w:styles>')
    return buffer.getvalue()


@pytest.fixture
def make_docx():
    return build_docx


async def _fetch(url: str, sql: str) -> list[tuple]:
    engine = create_engine(url)
    try:
        async with engine.connect() as connection:
            return [tuple(row) for row in await connection.execute(sql_text(sql))]
    finally:
        await engine.dispose()


@pytest.fixture
def query(db):
    """Run a SQL query against the test database and return its rows."""
    return lambda sql: asyncio.run(_fetch(db, sql))


@pytest.fixture
def client(db):
    from ragolex.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def embedder(client):
    """A stand-in embedding model for the app."""
    fake = FakeEmbedder()
    client.app.dependency_overrides[get_embedder] = lambda: fake
    return fake


@pytest.fixture
def llm(client):
    """A stand-in answer model for the app, answering from the first source."""
    fake = FakeLLM("Each chunk gets an embedding vector [1].")
    client.app.dependency_overrides[get_llm] = lambda: fake
    return fake


@pytest.fixture
def run_jobs(db, files_dir):
    """Run due jobs with a worker; returns whether each run found one."""
    def run(embedder=None, times=1, **options):
        embedder = embedder if embedder is not None else FakeEmbedder()

        async def work():
            engine = create_engine(db)
            try:
                runner = JobRunner(unit_of_work_factory(create_session_factory(engine)),
                                   FileStorage(root=files_dir), default_loader_registry(),
                                   embedder, batch_size=2, **options)
                return [await runner.run_next() for _ in range(times)]
            finally:
                await engine.dispose()

        return asyncio.run(work())
    return run
