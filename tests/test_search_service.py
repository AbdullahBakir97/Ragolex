import pytest

from ragolex.core.errors import EmbeddingFailed, ProjectNotFound
from ragolex.domain.models import Chunk
from ragolex.services.indexing_service import IndexingService
from ragolex.services.search_service import SearchService

from .fakes import FakeEmbedder, FakeUnitOfWork

pytestmark = pytest.mark.anyio

TEXTS = ["Cats purr and sleep all day.",
         "Postgres stores vectors with pgvector.",
         "Dogs bark at cats."]


@pytest.fixture
async def uow():
    uow = FakeUnitOfWork()
    project = await uow.projects.get_or_create("p1")
    record = await uow.files.add(project_id=project.id, key="a_notes.txt", original_name="notes.txt",
                                 content_type="text/plain", size_bytes=0)
    await uow.chunks.replace_for_file(record, [Chunk(i, text) for i, text in enumerate(TEXTS)])
    return uow


async def index(uow):
    await IndexingService(uow, FakeEmbedder(), batch_size=10).index("p1")


async def test_returns_the_best_matches_first(uow):
    await index(uow)
    embedder = FakeEmbedder()

    hits = await SearchService(uow, embedder).search("p1", "vectors in postgres", top_k=2)

    assert [hit.chunk.text for hit in hits][0] == TEXTS[1]
    assert len(hits) == 2 and hits[0].score > hits[1].score
    assert hits[0].file_key == "a_notes.txt"
    assert embedder.calls == [["vectors in postgres"]]


async def test_min_score_drops_weak_matches(uow):
    await index(uow)

    hits = await SearchService(uow, FakeEmbedder()).search("p1", "cats", top_k=10, min_score=0.3)

    assert {hit.chunk.text for hit in hits} == {TEXTS[0], TEXTS[2]}


async def test_project_without_indexed_chunks_returns_nothing_without_embedding(uow):
    embedder = FakeEmbedder()

    assert await SearchService(uow, embedder).search("p1", "cats", top_k=5) == []
    assert embedder.calls == []


async def test_unknown_project(uow):
    with pytest.raises(ProjectNotFound):
        await SearchService(uow, FakeEmbedder()).search("missing", "cats", top_k=5)


async def test_embedding_failures_propagate(uow):
    await index(uow)

    with pytest.raises(EmbeddingFailed):
        await SearchService(uow, FakeEmbedder(fail_on_call=1)).search("p1", "cats", top_k=5)


class FakeReranker:
    """Scores texts by a fixed table; ``fail`` makes it fail like a server that is down."""

    model = "fake-reranker"

    def __init__(self, scores: dict[str, float], fail: bool = False):
        self.scores = scores
        self.fail = fail
        self.calls: list[list[str]] = []

    async def rerank(self, query, texts):
        from ragolex.core.errors import RerankFailed

        self.calls.append(list(texts))
        if self.fail:
            raise RerankFailed("fake failure")
        return [self.scores.get(text, 0.0) for text in texts]


async def test_a_reranker_reorders_more_candidates_and_keeps_top_k(uow):
    await index(uow)
    reranker = FakeReranker({"Dogs bark at cats.": 0.9, "Cats purr and sleep all day.": 0.1})

    hits = await SearchService(uow, FakeEmbedder(), reranker=reranker,
                               rerank_candidates=3).search("p1", "cats", top_k=1)

    assert [hit.chunk.text for hit in hits] == ["Dogs bark at cats."]
    # It saw all three candidates, not just the one asked for.
    assert len(reranker.calls[0]) == 3


async def test_when_reranking_fails_the_search_order_stays(uow, caplog):
    await index(uow)
    expected = await SearchService(uow, FakeEmbedder()).search("p1", "cats", top_k=2)

    hits = await SearchService(uow, FakeEmbedder(), reranker=FakeReranker({}, fail=True)).search(
        "p1", "cats", top_k=2)

    assert hits == expected
    assert "Reranking with fake-reranker failed" in caplog.text
