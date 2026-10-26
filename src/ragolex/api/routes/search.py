from fastapi import APIRouter

from ragolex.api.dependencies import READ, SearchServiceDep
from ragolex.api.schemas import (
    ProjectId,
    SearchRequest,
    SearchResponse,
    SearchResult,
    error_responses,
)
from ragolex.core.errors import (
    EmbeddingFailed,
    EmbeddingNotConfigured,
    FileNotFound,
    ProjectNotFound,
)
from ragolex.domain.signals import ResponseSignal

router = APIRouter(prefix="/api/v1/search", tags=["search"], dependencies=[READ])


@router.post(
    "/{project_id}",
    summary="Find the chunks that best match a question",
    description="Searches the project's indexed chunks (see POST /api/v1/index/{project_id}), "
                "best match first: by meaning and by the query's words with SEARCH_MODE=hybrid "
                "(the default), by meaning only with vector. Scores are the cosine similarity "
                "either way. Chunks that are not indexed yet are not found.",
    responses=error_responses(ProjectNotFound, FileNotFound, EmbeddingFailed,
                              EmbeddingNotConfigured),
)
async def search_project(project_id: ProjectId, request: SearchRequest,
                         service: SearchServiceDep) -> SearchResponse:
    filters = request.filters.to_filters() if request.filters else None
    hits = await service.search(project_id, request.query, top_k=request.top_k,
                                min_score=request.min_score, filters=filters)
    return SearchResponse(
        signal=ResponseSignal.SEARCH_SUCCESS,
        results=[SearchResult(file_id=hit.file_key, chunk_index=hit.chunk.index, score=hit.score,
                              text=hit.chunk.text, metadata=hit.chunk.metadata)
                 for hit in hits])
