from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from ragolex.api.dependencies import READ, WRITE, SourceServiceDep
from ragolex.api.schemas import (
    Pagination,
    ProjectId,
    SourceIdPath,
    SourceListResponse,
    SourcePageResponse,
    SourcePagesResponse,
    SourceRequest,
    SourceResponse,
    error_responses,
)
from ragolex.core.errors import (
    ConnectionNotFound,
    ConnectionWrongKind,
    ProjectNotFound,
    SourceNotFound,
    SourceUrlNotAllowed,
)
from ragolex.domain.models import Source

router = APIRouter(prefix="/api/v1/projects", tags=["sources"])


def _source(source: Source) -> SourceResponse:
    return SourceResponse(id=source.id, kind=source.kind, url=source.url,
                          connection_id=source.connection_id, max_pages=source.max_pages,
                          sync_interval_hours=source.sync_interval_hours,
                          pages_count=source.pages_count, syncing=source.syncing,
                          last_synced_at=source.last_synced_at, next_sync_at=source.next_sync_at,
                          last_error=source.last_error, tags=list(source.tags),
                          created_at=source.created_at)


@router.post(
    "/{project_id}/sources", dependencies=[WRITE], status_code=status.HTTP_201_CREATED,
    summary="Keep a website's pages, a feed's entries, a GitHub repository's documents, "
            "Notion pages or a Google Drive folder's files",
    description="A website's pages under the URL's folder are crawled, following their links "
                "(robots.txt is obeyed); a feed's entries are read; a GitHub repository's "
                "documents are listed and fetched; Notion pages and Google Drive files are "
                "read through one of the workspace's connections. Each page is stored as a file and processed "
                "and indexed in the background; then again every `sync_interval_hours`, adding "
                "new pages, replacing changed ones and deleting the ones that are gone (a "
                "feed's older entries stay). The first sync starts at once. The project is "
                "created if it has no files yet.",
    responses=error_responses(SourceUrlNotAllowed, ConnectionNotFound, ConnectionWrongKind))
async def create_source(project_id: ProjectId, request: SourceRequest,
                        service: SourceServiceDep) -> SourceResponse:
    return _source(await service.create(project_id, str(request.url), request.max_pages,
                                        request.sync_interval_hours, request.tags,
                                        request.kind, request.connection_id))


@router.get("/{project_id}/sources", dependencies=[READ], summary="List a project's sources",
            responses=error_responses(ProjectNotFound))
async def list_sources(project_id: ProjectId, service: SourceServiceDep) -> SourceListResponse:
    return SourceListResponse(items=[_source(s) for s in await service.list(project_id)])


@router.get("/{project_id}/sources/{source_id}", dependencies=[READ], summary="A source",
            responses=error_responses(ProjectNotFound, SourceNotFound))
async def get_source(project_id: ProjectId, source_id: SourceIdPath,
                     service: SourceServiceDep) -> SourceResponse:
    return _source(await service.get(project_id, str(source_id)))


@router.get("/{project_id}/sources/{source_id}/pages", dependencies=[READ],
            summary="The pages a source stored, in URL order",
            responses=error_responses(ProjectNotFound, SourceNotFound))
async def list_source_pages(project_id: ProjectId, source_id: SourceIdPath,
                            page: Annotated[Pagination, Depends()],
                            service: SourceServiceDep) -> SourcePagesResponse:
    source, pages = await service.pages(project_id, str(source_id), offset=page.offset,
                                        limit=page.limit)
    return SourcePagesResponse(
        total=source.pages_count, offset=page.offset, limit=page.limit,
        items=[SourcePageResponse(url=p.url, file_id=p.file_key, synced_at=p.synced_at)
               for p in pages])


@router.post("/{project_id}/sources/{source_id}/sync", dependencies=[WRITE],
             status_code=status.HTTP_202_ACCEPTED, summary="Sync a source now",
             description="A worker syncs it as soon as one is free.",
             responses=error_responses(ProjectNotFound, SourceNotFound))
async def sync_source(project_id: ProjectId, source_id: SourceIdPath,
                      service: SourceServiceDep) -> SourceResponse:
    return _source(await service.sync(project_id, str(source_id)))


@router.delete("/{project_id}/sources/{source_id}", dependencies=[WRITE],
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Stop syncing a source, and delete the files it stored",
               responses=error_responses(ProjectNotFound, SourceNotFound))
async def delete_source(
    project_id: ProjectId, source_id: SourceIdPath, service: SourceServiceDep,
    keep_files: Annotated[bool, Query(description="Keep the pages' files in the project.")] = False,
) -> Response:
    await service.delete(project_id, str(source_id), keep_files=keep_files)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
