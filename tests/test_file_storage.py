import os

import pytest

from ragolex.core.errors import FileNotFound
from ragolex.storage.file_storage import FileStorage


@pytest.fixture
def storage(tmp_path):
    return FileStorage(root=tmp_path / "files")


def test_reserve_file_creates_empty_file_with_clean_unique_id(storage):
    file_id, path = storage.reserve_file("p1", "my notes.txt")

    assert file_id.endswith("_my_notes.txt")
    assert path == storage.root / "p1" / file_id
    assert path.is_file() and path.read_bytes() == b""


def test_reserved_ids_are_unique(storage):
    ids = {storage.reserve_file("p1", "same.txt")[0] for _ in range(50)}

    assert len(ids) == 50


def test_get_file_path_returns_reserved_file(storage):
    file_id, path = storage.reserve_file("p1", "a.txt")

    assert storage.get_file_path("p1", file_id) == path


@pytest.mark.parametrize("file_id", ["missing.txt", "..", ".", "../p2/x.txt", "/etc/passwd"])
def test_get_file_path_rejects_missing_or_outside_files(storage, file_id):
    storage.reserve_file("p2", "x.txt")

    with pytest.raises(FileNotFound):
        storage.get_file_path("p1", file_id)


def test_get_file_path_rejects_symlink_out_of_project(storage, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    storage.reserve_file("p1", "a.txt")
    os.symlink(secret, storage.root / "p1" / "link.txt")

    with pytest.raises(FileNotFound):
        storage.get_file_path("p1", "link.txt")


@pytest.mark.parametrize("project_id", ["..", ".", "a/b", "/tmp"])
def test_project_id_cannot_escape_root(storage, project_id):
    with pytest.raises(ValueError):
        storage.reserve_file(project_id, "a.txt")


def test_files_and_project_folders_are_deleted_inside_the_root(tmp_path):
    storage = FileStorage(root=tmp_path / "files")
    file_id, path = storage.reserve_file("p1", "notes.txt")

    storage.delete_file("p1", file_id)
    storage.delete_file("p1", file_id)  # already gone: nothing happens
    assert not path.exists()

    with pytest.raises(FileNotFound):
        storage.delete_file("p1", "../../outside.txt")
    with pytest.raises(ValueError):
        storage.delete_project("..")

    storage.delete_project("p1")
    storage.delete_project("p1")  # already gone: nothing happens
    assert not (tmp_path / "files" / "p1").exists()
