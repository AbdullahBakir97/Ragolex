import pytest

from ragolex.core.errors import FileNotFound, ProjectNotFound
from ragolex.domain.models import Chunk
from ragolex.services.project_service import ProjectService

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.anyio


@pytest.fixture
async def uow():
    uow = FakeUnitOfWork()
    project = await uow.projects.get_or_create("demo")
    for key in ("a.txt", "b.txt"):
        await uow.files.add(project_id=project.id, key=key, original_name=key,
                            content_type="text/plain", size_bytes=1)
    first = await uow.files.get_by_key(project.id, "a.txt")
    await uow.chunks.replace_for_file(first, [Chunk(i, f"c{i}") for i in range(3)])
    return uow


async def test_summary_counts_files_and_chunks(uow):
    summary = await ProjectService(uow).get_summary("demo")

    assert (summary.project.name, summary.files_count, summary.chunks_count) == ("demo", 2, 3)
    assert summary.embedded_chunks_count == 0


async def test_summary_counts_indexed_chunks(uow):
    [first, *_] = await uow.chunks.list_unembedded(1, file_id=None, limit=10)
    await uow.chunks.set_embeddings({first.id: [1.0]})

    summary = await ProjectService(uow).get_summary("demo")

    assert (summary.chunks_count, summary.embedded_chunks_count) == (3, 1)


async def test_pages_report_total_and_window(uow):
    service = ProjectService(uow)

    files = await service.list_files("demo", offset=1, limit=5)
    chunks = await service.list_chunks("demo", "a.txt", offset=0, limit=2)

    assert ([f.key for f in files.items], files.total) == (["b.txt"], 2)
    assert ([c.index for c in chunks.items], chunks.total, chunks.limit) == ([0, 1], 3, 2)


async def test_unknown_project_and_file(uow):
    service = ProjectService(uow)

    with pytest.raises(ProjectNotFound):
        await service.get_summary("other")
    with pytest.raises(FileNotFound):
        await service.list_chunks("demo", "missing.txt", offset=0, limit=10)


async def test_projects_are_listed_by_name(uow):
    await uow.projects.get_or_create("alpha")
    await uow.projects.get_or_create("zeta")

    page = await ProjectService(uow).list_projects(offset=1, limit=1)

    assert ([p.name for p in page.items], page.total) == (["demo"], 3)
