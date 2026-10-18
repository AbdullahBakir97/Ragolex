"""Backups are only as good as their restores: back up, restore elsewhere, and search the copy."""

import asyncio
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import create_async_engine

from mini_rag.api.dependencies import get_embedder
from mini_rag.core.config import get_settings

from .conftest import TEST_DATABASE_URL
from .fakes import FakeEmbedder
from .test_ask_api import upload_process_and_index

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "backup.sh"

# Skipped where PostgreSQL's client tools are missing, except in CI, which must run it.
pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("pg_dump", "pg_restore", "psql", "sha256sum"))
    and not os.environ.get("CI"),
    reason="needs PostgreSQL's client tools (pg_dump, pg_restore, psql)")

_target = make_url(TEST_DATABASE_URL)
RESTORE_URL = _target.set(database=f"{_target.database}_restore").render_as_string(
    hide_password=False)


async def _recreate(url: str) -> None:
    target = make_url(url)
    engine = create_async_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                sql_text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
            await connection.execute(sql_text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await engine.dispose()


@pytest.fixture
def empty_database():
    """A new, empty database to restore into."""
    asyncio.run(_recreate(RESTORE_URL))
    return RESTORE_URL


def run(*args: str, database: str, files: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database, "FILES_DIR": str(files)}
    return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True,
                          timeout=120)


def search(client, query="embedding vector"):
    response = client.post("/api/v1/search/demo", json={"query": query, "top_k": 3})
    assert response.status_code == 200, response.text
    return [(hit["file_id"], hit["chunk_index"], hit["text"]) for hit in response.json()["results"]]


@pytest.fixture
def backed_up(client, db, embedder, files_dir, tmp_path):
    """The demo project, indexed, and an archive of it."""
    upload_process_and_index(client)
    created = run("create", str(tmp_path / "backups"), database=db, files=files_dir)
    assert created.returncode == 0, created.stderr
    [archive] = (tmp_path / "backups").glob("mini-rag-*.tar.gz")
    return archive, search(client)


def test_a_backup_restores_into_a_working_copy(backed_up, empty_database, files_dir, tmp_path,
                                               monkeypatch):
    archive, results_before = backed_up
    restored_files = tmp_path / "restored-files"

    restored = run("restore", str(archive), database=empty_database, files=restored_files)

    assert restored.returncode == 0, restored.stderr
    assert "schema_revision=" in restored.stdout and "files=1" in restored.stdout
    # The files are the same, byte for byte.
    originals = {p.relative_to(files_dir): p.read_bytes() for p in files_dir.rglob("*") if p.is_file()}
    copies = {p.relative_to(restored_files): p.read_bytes()
              for p in restored_files.rglob("*") if p.is_file()}
    assert copies == originals and copies

    # An app on the restored database and files finds the same passages, embeddings included.
    monkeypatch.setenv("DATABASE_URL", empty_database)
    monkeypatch.setenv("FILES_DIR", str(restored_files))
    get_settings.cache_clear()
    from mini_rag.main import create_app

    with TestClient(create_app()) as restored_client:
        restored_client.app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        assert search(restored_client) == results_before
        files = restored_client.get("/api/v1/projects/demo/files").json()
        assert files["total"] == 1


def test_a_restore_never_mixes_into_existing_data(backed_up, db, files_dir):
    archive, _ = backed_up

    refused = run("restore", str(archive), database=db, files=files_dir)

    assert refused.returncode != 0
    assert "the database has tables already" in refused.stderr


def test_a_damaged_archive_is_refused(backed_up, empty_database, tmp_path):
    archive, _ = backed_up
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    (unpacked / "files.tar").write_bytes(b"not the files")
    damaged = tmp_path / "damaged.tar.gz"
    with tarfile.open(damaged, "w:gz") as tar:
        for name in ("database.dump", "files.tar", "manifest.txt", "SHA256SUMS"):
            tar.add(unpacked / name, arcname=name)

    refused = run("restore", str(damaged), database=empty_database, files=tmp_path / "files")

    assert refused.returncode != 0
    assert "checksums do not match" in refused.stderr


def test_force_restores_over_a_disaster(backed_up, client, db, files_dir):
    archive, results_before = backed_up
    assert client.delete("/api/v1/projects/demo").status_code == 204
    assert not any(p.is_file() for p in files_dir.rglob("*"))

    restored = run("restore", str(archive), "--force", database=db, files=files_dir)
    assert restored.returncode == 0, restored.stderr

    # The API is restarted after a restore: the restore recreates the vector
    # extension, whose type a running app's connections still know by its old id.
    from mini_rag.main import create_app

    with TestClient(create_app()) as restarted:
        restarted.app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        assert search(restarted) == results_before
