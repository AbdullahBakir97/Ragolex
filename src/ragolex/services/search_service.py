import logging
from typing import Literal

from ragolex.core.errors import FileNotFound, ProjectNotFound, RerankFailed
from ragolex.domain.embedder import Embedder
from ragolex.domain.models import ScoredChunk, SearchFilters
from ragolex.domain.repositories import UnitOfWork
from ragolex.domain.reranker import Reranker

logger = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "vector"]


class SearchService:
    """Finds the chunks of a project that best match a question.

    In hybrid mode, chunks that share the question's words count as well as
    chunks close to it in meaning; in vector mode only meaning counts. With
    a reranker, the best ``rerank_candidates`` results are reordered by it
    and the best ``top_k`` of them kept; if it fails, the search order stays.
    """

    def __init__(self, uow: UnitOfWork, embedder: Embedder, mode: SearchMode = "hybrid",
                 reranker: Reranker | None = None, rerank_candidates: int = 20):
        self.uow = uow
        self.embedder = embedder
        self.mode = mode
        self.reranker = reranker
        self.rerank_candidates = rerank_candidates

    async def search(self, project_name: str, query: str, top_k: int,
                     min_score: float | None = None,
                     filters: SearchFilters | None = None) -> list[ScoredChunk]:
        """The best matching indexed chunks, best first.

        Chunks that are not indexed yet are not searched. A project with no
        indexed chunks returns no results without calling the embedder.
        ``filters`` narrows the chunks searched; a file it names that the
        project does not have raises FileNotFound.
        """
        project = await self.uow.projects.get_by_name(project_name)
        if project is None:
            raise ProjectNotFound()
        for key in filters.file_keys if filters else ():
            if await self.uow.files.get_by_key(project.id, key) is None:
                raise FileNotFound(f"No file {key!r} in the project")
        if await self.uow.chunks.count_embedded_for_project(project.id) == 0:
            return []

        [vector] = await self.embedder.embed([query])
        fetched = max(top_k, self.rerank_candidates) if self.reranker else top_k
        hits = await self.uow.chunks.search(
            project.id, vector, top_k=fetched, min_score=min_score,
            query=query if self.mode == "hybrid" else None, filters=filters)
        if self.reranker is not None and len(hits) > 1:
            hits = await self._rerank(self.reranker, query, hits)
        return hits[:top_k]

    @staticmethod
    async def _rerank(reranker: Reranker, query: str,
                      hits: list[ScoredChunk]) -> list[ScoredChunk]:
        try:
            scores = await reranker.rerank(query, [hit.chunk.text for hit in hits])
        except RerankFailed:
            logger.warning("Reranking with %s failed; the search order is kept.",
                           reranker.model, exc_info=True)
            return hits
        # A stable sort keeps the search order between equal scores.
        order = sorted(range(len(hits)), key=lambda index: -scores[index])
        return [hits[index] for index in order]
