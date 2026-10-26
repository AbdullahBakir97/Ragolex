import asyncio

import pytest

from ragolex.core.errors import FileTooLarge, UnsupportedFileType, UploadFailed
from ragolex.services.upload_service import UploadService
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeUnitOfWork


class FakeStream:
    """Serves `data` in reads; optionally fails after `fail_after` reads."""

    def __init__(self, data: bytes, fail_after: int | None = None,
                 error: BaseException | None = None):
        self.data, self.fail_after, self.reads = data, fail_after, 0
        self.error = error or OSError("disk failure")

    async def read(self, size: int = -1) -> bytes:
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise self.error
        self.reads += 1
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


@pytest.fixture
def storage(tmp_path):
    return FileStorage(root=tmp_path / "files")


@pytest.fixture
def uow():
    return FakeUnitOfWork()


@pytest.fixture
def service(storage, uow):
    return UploadService(storage=storage, uow=uow, allowed_types=["text/plain"],
                         max_bytes=100, read_size=10)


def save(service, data=b"hello", content_type="text/plain", declared_size=None,
         **stream_options):
    stream = FakeStream(data, **stream_options)
    return asyncio.run(service.save("p1", "notes.txt", content_type, stream,
                                    declared_size=declared_size)).file_id


def stored_files(storage):
    return [path for path in storage.root.rglob("*") if path.is_file()]


def test_save_streams_file_to_storage(service, storage):
    data = b"x" * 95

    file_id = save(service, data)

    assert storage.get_file_path("p1", file_id).read_bytes() == data


def test_rejects_unsupported_type_before_touching_disk(service, storage):
    with pytest.raises(UnsupportedFileType):
        save(service, content_type="image/png")

    assert not storage.root.exists()


@pytest.mark.parametrize("declared", [None, "", "application/octet-stream", "text/plain; charset=utf-8"])
def test_a_missing_or_generic_type_is_taken_from_the_extension(service, uow, declared):
    save(service, content_type=declared)

    [record] = uow.files.records
    assert record.content_type == "text/plain"


def test_rejects_declared_size_over_limit(service, storage):
    with pytest.raises(FileTooLarge):
        save(service, declared_size=101)

    assert stored_files(storage) == []


def test_enforces_limit_on_bytes_actually_received(service, storage):
    # The client claims 5 bytes (or nothing) but sends 101.
    for declared in (5, None):
        with pytest.raises(FileTooLarge):
            save(service, b"x" * 101, declared_size=declared)

    assert stored_files(storage) == []


def test_exactly_the_limit_is_accepted(service, storage):
    file_id = save(service, b"x" * 100)

    assert storage.get_file_path("p1", file_id).stat().st_size == 100


def test_stream_failure_becomes_upload_failed_and_cleans_up(service, storage):
    with pytest.raises(UploadFailed) as raised:
        save(service, b"x" * 50, fail_after=2)

    assert isinstance(raised.value.__cause__, OSError)
    assert stored_files(storage) == []


def test_cancelled_upload_leaves_nothing_behind(service, storage):
    with pytest.raises(asyncio.CancelledError):
        save(service, b"x" * 50, fail_after=1, error=asyncio.CancelledError())

    assert stored_files(storage) == []


def test_upload_is_recorded_and_committed(service, uow):
    file_id = save(service, b"x" * 42)

    project = uow.projects.by_name["p1"]
    [record] = uow.files.records
    assert (record.project_id, record.key, record.original_name, record.content_type,
            record.size_bytes) == (project.id, file_id, "notes.txt", "text/plain", 42)
    assert uow.commits == 1


def test_rejected_upload_is_not_committed(service, uow):
    with pytest.raises(FileTooLarge):
        save(service, b"x" * 101)

    assert uow.files.records == [] and uow.commits == 0


@pytest.mark.parametrize("failure", ["add", "commit"])
def test_database_failure_removes_the_stored_file(service, uow, storage, failure):
    error = RuntimeError("database is down")
    if failure == "add":
        uow.files.fail_with = error
    else:
        uow.fail_commit_with = error

    with pytest.raises(UploadFailed) as raised:
        save(service)

    assert raised.value.__cause__ is error
    assert stored_files(storage) == []


def test_the_same_content_is_stored_once(service, storage, uow):
    import hashlib

    first = asyncio.run(service.save("p1", "notes.txt", "text/plain", FakeStream(b"hello")))
    again = asyncio.run(service.save("p1", "copy.txt", "text/plain", FakeStream(b"hello")))
    other = asyncio.run(service.save("p1", "other.txt", "text/plain", FakeStream(b"world")))

    assert (first.duplicate, again.duplicate, other.duplicate) == (False, True, False)
    assert again.file_id == first.file_id
    assert len(stored_files(storage)) == 2
    assert uow.files.records[0].content_sha256 == hashlib.sha256(b"hello").hexdigest()


def test_the_same_content_in_another_project_is_stored(service, storage):
    first = asyncio.run(service.save("p1", "notes.txt", "text/plain", FakeStream(b"hello")))
    second = asyncio.run(service.save("p2", "notes.txt", "text/plain", FakeStream(b"hello")))

    assert not second.duplicate
    assert second.file_id != first.file_id
