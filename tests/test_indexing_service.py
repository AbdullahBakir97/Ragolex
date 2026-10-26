import pytest

from ragolex.core.errors import EmbeddingFailed, FileNotFound, ProjectNotFound
from ragolex.domain.models import Chunk
from ragolex.services.indexing_service import IndexingService

from .fakes import FakeEmbedder, FakeUnitOfWork

pytestmark = pytest.mark.anyio


@pytest.fixture
def uow():
    return FakeUnitOfWork()


async def add_chunks(uow, key, texts, project="p1"):
    project = await uow.projects.get_or_create(project)
    record = await uow.files.add(project_id=project.id, key=key, original_name=key,
                                 content_type="text/plain", size_bytes=0)
    await uow.chunks.replace_for_file(record, [Chunk(i, text) for i, text in enumerate(texts)])
    return record


async def test_embeds_all_chunks_in_batches_and_commits_each(uow):
    await add_chunks(uow, "a_1.txt", ["a", "b", "c"])
    await add_chunks(uow, "b_2.txt", ["d", "e"])
    embedder = FakeEmbedder()

    result = await IndexingService(uow, embedder, batch_size=2).index("p1")

    assert (result.embedded_count, result.chunks_count) == (5, 5)
    assert embedder.calls == [["a", "b"], ["c", "d"], ["e"]]
    assert uow.commits == 3
    assert await uow.chunks.count_embedded_for_project(1) == 5


async def test_indexing_again_embeds_only_new_chunks(uow):
    await add_chunks(uow, "a_1.txt", ["a", "b"])
    embedder = FakeEmbedder()
    service = IndexingService(uow, embedder, batch_size=10)
    await service.index("p1")
    await add_chunks(uow, "b_2.txt", ["new"])

    again = await service.index("p1")
    nothing_left = await service.index("p1")

    assert (again.embedded_count, again.chunks_count) == (1, 3)
    assert (nothing_left.embedded_count, nothing_left.chunks_count) == (0, 3)
    assert embedder.calls == [["a", "b"], ["new"]]


async def test_a_failure_keeps_finished_batches_and_a_retry_continues(uow):
    await add_chunks(uow, "a_1.txt", ["a", "b", "c"])
    service = IndexingService(uow, FakeEmbedder(fail_on_call=2), batch_size=1)

    with pytest.raises(EmbeddingFailed):
        await service.index("p1")
    assert await uow.chunks.count_embedded_for_project(1) == 1

    retry = await IndexingService(uow, FakeEmbedder(), batch_size=1).index("p1")
    assert retry.embedded_count == 2
    assert await uow.chunks.count_embedded_for_project(1) == 3


async def test_can_index_a_single_file(uow):
    await add_chunks(uow, "a_1.txt", ["a", "b"])
    await add_chunks(uow, "b_2.txt", ["c"])
    embedder = FakeEmbedder()

    result = await IndexingService(uow, embedder, batch_size=10).index("p1", file_key="b_2.txt")

    assert (result.embedded_count, result.chunks_count) == (1, 1)
    assert embedder.calls == [["c"]]


async def test_other_projects_are_left_alone(uow):
    await add_chunks(uow, "a_1.txt", ["mine"], project="p1")
    await add_chunks(uow, "b_2.txt", ["theirs"], project="p2")
    embedder = FakeEmbedder()

    await IndexingService(uow, embedder, batch_size=10).index("p1")

    assert embedder.calls == [["mine"]]


async def test_project_without_chunks_needs_no_embedding_calls(uow):
    await uow.projects.get_or_create("p1")
    embedder = FakeEmbedder()

    result = await IndexingService(uow, embedder, batch_size=10).index("p1")

    assert (result.embedded_count, result.chunks_count) == (0, 0)
    assert embedder.calls == []


async def test_unknown_project_or_file(uow):
    await add_chunks(uow, "a_1.txt", ["a"])
    service = IndexingService(uow, FakeEmbedder(), batch_size=10)

    with pytest.raises(ProjectNotFound):
        await service.index("missing")
    with pytest.raises(FileNotFound):
        await service.index("p1", file_key="missing.txt")
