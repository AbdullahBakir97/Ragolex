import pytest

from ragolex.storage.file_storage import clean_file_name


def upload(client, project_id, name="notes.txt", content=b"hello", content_type="text/plain"):
    return client.post(
        f"/api/v1/data/upload/{project_id}",
        files={"file": (name, content, content_type)},
    )


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_welcome_returns_app_info(client):
    response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Hello All",
        "app_name": "Ragolex-test",
        "app_version": "0.0.1",
    }


def test_upload_stores_file_under_project(client, files_dir):
    response = upload(client, "project_1", name="my notes.txt", content=b"some text")

    assert response.status_code == 200
    body = response.json()
    assert body["signal"] == "file_uploaded_successfully"
    assert body["file_id"].endswith("_my_notes.txt")
    assert (files_dir / "project_1" / body["file_id"]).read_bytes() == b"some text"


def test_upload_generates_unique_file_ids(client):
    first = upload(client, "p1", content=b"hello").json()["file_id"]
    second = upload(client, "p1", content=b"world").json()["file_id"]

    assert first != second


def test_uploading_the_same_content_again_returns_the_file_already_there(client, files_dir):
    first = upload(client, "p1", name="notes.txt").json()
    again = upload(client, "p1", name="renamed.txt").json()

    assert first["signal"] == "file_uploaded_successfully"
    assert again == {"signal": "file_already_uploaded", "file_id": first["file_id"]}
    assert len(list((files_dir / "p1").iterdir())) == 1


def test_upload_rejects_unsupported_type(client, files_dir):
    response = upload(client, "p1", name="image.png", content_type="image/png")

    assert response.status_code == 415
    assert response.json() == {"signal": "file_type_not_supported"}
    assert not (files_dir / "p1").exists()


def test_upload_rejects_oversized_file(client):
    # FILE_MAX_SIZE is 1 MB in the test settings.
    response = upload(client, "p1", content=b"x" * (1024 * 1024 + 1))

    assert response.status_code == 413
    assert response.json() == {"signal": "file_size_exceeded"}


@pytest.mark.parametrize("project_id", ["%2E%2E", "a.b", "x" * 65])
def test_upload_rejects_unsafe_project_id(client, files_dir, project_id):
    response = upload(client, project_id)

    assert response.status_code == 422
    assert list(files_dir.parent.rglob("*.txt")) == []


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("my notes.txt", "my_notes.txt"),
        ("  padded name.txt  ", "padded_name.txt"),
        ("../../etc/passwd", "....etcpasswd"),
        ("résumé (final).pdf", "résumé_final.pdf"),
        ("", "file"),
        ("%%%", "file"),
    ],
)
def test_clean_file_name(original, expected):
    assert clean_file_name(original) == expected


def test_upload_disk_failure_is_a_server_error(client, files_dir, monkeypatch, caplog):
    def failing_open(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr("ragolex.services.upload_service.aiofiles.open", failing_open)

    response = upload(client, "p1")

    assert response.status_code == 500
    assert response.json() == {"signal": "file_upload_failed"}
    assert "No space left on device" in caplog.text
    assert [p for p in files_dir.rglob("*") if p.is_file()] == []


def test_upload_records_project_and_file_in_database(client, query):
    file_id = upload(client, "project_1", name="my notes.txt", content=b"some text").json()["file_id"]
    upload(client, "project_1")

    assert query("SELECT name FROM projects") == [("project_1",)]
    assert query("SELECT key, original_name, content_type, size_bytes FROM files ORDER BY id")[0] == (
        file_id, "my notes.txt", "text/plain", 9)
    assert query("SELECT count(*) FROM files") == [(2,)]


def test_rejected_upload_leaves_no_database_rows(client, query):
    upload(client, "p1", name="image.png", content_type="image/png")
    upload(client, "p1", content=b"x" * (1024 * 1024 + 1))

    assert query("SELECT count(*) FROM projects") == [(0,)]
    assert query("SELECT count(*) FROM files") == [(0,)]
