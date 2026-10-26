import pytest

from ragolex.core.errors import (
    FileNotFound,
    NoTextExtracted,
    ProcessingFailed,
    UnsupportedFileType,
)
from ragolex.domain.models import Document
from ragolex.loaders.registry import LoaderRegistry
from ragolex.services.processing_service import ProcessingService
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.anyio


class FakeLoader:
    def __init__(self, documents=None, error=None):
        self.documents, self.error, self.calls = documents or [], error, []

    def load(self, path, source):
        self.calls.append((path, source))
        if self.error:
            raise self.error
        return self.documents


@pytest.fixture
def storage(tmp_path):
    return FileStorage(root=tmp_path / "files")


@pytest.fixture
def uow():
    return FakeUnitOfWork()


async def uploaded(storage, uow, name="a.txt"):
    """Store and record a file the way UploadService does."""
    project = await uow.projects.get_or_create("p1")
    key, path = storage.reserve_file("p1", name)
    record = await uow.files.add(project_id=project.id, key=key, original_name=name,
                                 content_type="text/plain", size_bytes=0)
    return record, path


def make_service(storage, uow, loader):
    return ProcessingService(storage=storage, loaders=LoaderRegistry({".txt": loader}), uow=uow)


async def test_chunks_are_numbered_stored_and_committed(storage, uow):
    loader = FakeLoader([
        Document("alpha beta gamma delta", {"source": "s", "page": 1}),
        Document("epsilon zeta", {"source": "s", "page": 2}),
    ])
    record, path = await uploaded(storage, uow)

    count = await make_service(storage, uow, loader).process("p1", record.key, 12, 0)

    assert count == 3
    assert loader.calls == [(path, record.key)]
    stored = await uow.chunks.list_for_file(record.id, offset=0, limit=10)
    assert [(c.index, c.text, c.metadata) for c in stored] == [
        (0, "alpha beta", {"source": "s", "page": 1}),
        (1, "gamma delta", {"source": "s", "page": 1}),
        (2, "epsilon zeta", {"source": "s", "page": 2}),
    ]
    assert uow.commits == 1


@pytest.mark.parametrize(("project", "key"), [("p1", "nope.txt"), ("other", "a.txt")])
async def test_unknown_project_or_file_is_not_found(storage, uow, project, key):
    loader = FakeLoader()
    await uploaded(storage, uow)

    with pytest.raises(FileNotFound):
        await make_service(storage, uow, loader).process(project, key, 100, 0)
    assert loader.calls == []


async def test_unsupported_type(storage, uow):
    record, _ = await uploaded(storage, uow, name="a.md")

    with pytest.raises(UnsupportedFileType):
        await make_service(storage, uow, FakeLoader()).process("p1", record.key, 100, 0)


async def test_loader_errors_become_processing_failed_and_nothing_is_saved(storage, uow):
    record, _ = await uploaded(storage, uow)
    cause = RuntimeError("corrupt")

    with pytest.raises(ProcessingFailed) as raised:
        await make_service(storage, uow, FakeLoader(error=cause)).process("p1", record.key, 100, 0)

    assert raised.value.__cause__ is cause
    assert await uow.chunks.count_for_file(record.id) == 0


async def test_blank_documents_raise_no_text(storage, uow):
    record, _ = await uploaded(storage, uow)
    loader = FakeLoader([Document("   "), Document("\n\n")])

    with pytest.raises(NoTextExtracted):
        await make_service(storage, uow, loader).process("p1", record.key, 100, 0)
