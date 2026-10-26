from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ragolex.api.dependencies import (
    ADMIN,
    READ,
    WRITE,
    AssistantServiceDep,
    DeletionServiceDep,
    ProjectServiceDep,
    TagServiceDep,
)
from ragolex.api.schemas import (
    AssistantResponse,
    AssistantUpdateRequest,
    ChunkListResponse,
    ChunkResponse,
    FileIdPath,
    FileListResponse,
    FileResponse,
    FileTagsRequest,
    Pagination,
    ProjectId,
    ProjectListItem,
    ProjectListResponse,
    ProjectResponse,
    ProjectUsageResponse,
    TagListResponse,
    TagQuery,
    TagResponse,
    error_responses,
)
from ragolex.core.errors import FileNotFound, ProjectNotFound, TagInvalid
from ragolex.domain.models import FileRecord, Project
from ragolex.services.tag_service import clean_tags

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

PaginationDep = Annotated[Pagination, Depends()]


def _file_response(record: FileRecord) -> FileResponse:
    return FileResponse(file_id=record.key, original_name=record.original_name,
                        content_type=record.content_type, size_bytes=record.size_bytes,
                        created_at=record.created_at, tags=list(record.tags))


@router.get("", dependencies=[READ], summary="List projects in name order")
async def list_projects(page: PaginationDep, service: ProjectServiceDep) -> ProjectListResponse:
    result = await service.list_projects(offset=page.offset, limit=page.limit)
    return ProjectListResponse(
        total=result.total, offset=result.offset, limit=result.limit,
        items=[ProjectListItem(name=project.name, created_at=project.created_at)
               for project in result.items])


@router.get("/{project_id}", dependencies=[READ],
            summary="Project details with file, chunk and index counts",
            responses=error_responses(ProjectNotFound))
async def get_project(project_id: ProjectId, service: ProjectServiceDep) -> ProjectResponse:
    summary = await service.get_summary(project_id)
    return ProjectResponse(name=summary.project.name, created_at=summary.project.created_at,
                           files_count=summary.files_count, chunks_count=summary.chunks_count,
                           embedded_chunks_count=summary.embedded_chunks_count)


def _assistant(project: Project) -> AssistantResponse:
    return AssistantResponse(name=project.assistant_name, instructions=project.instructions)


@router.get("/{project_id}/assistant", dependencies=[READ],
            summary="The project's assistant: its name and its owner's instructions",
            responses=error_responses(ProjectNotFound))
async def get_assistant(project_id: ProjectId, service: AssistantServiceDep) -> AssistantResponse:
    return _assistant(await service.get(project_id))


@router.patch("/{project_id}/assistant", dependencies=[ADMIN],
              summary="Change the project's assistant",
              description="Only the fields sent change; null or blank clears one. Answers "
                          "follow the instructions in the tone and style they set, but always "
                          "answer from the documents only, with citations.",
              responses=error_responses(ProjectNotFound))
async def update_assistant(project_id: ProjectId, request: AssistantUpdateRequest,
                           service: AssistantServiceDep) -> AssistantResponse:
    changes = request.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["assistant_name"] = changes.pop("name")
    return _assistant(await service.update(project_id, changes))


@router.get("/{project_id}/usage", dependencies=[READ],
            summary="Token usage and cost of the project's answers",
            responses=error_responses(ProjectNotFound))
async def get_usage(project_id: ProjectId, service: ProjectServiceDep) -> ProjectUsageResponse:
    totals = await service.get_usage(project_id)
    return ProjectUsageResponse(answers=totals.answers, answered=totals.answered,
                                input_tokens=totals.input_tokens,
                                output_tokens=totals.output_tokens, cost_usd=totals.cost_usd,
                                unpriced_answers=totals.unpriced_answers)


@router.get("/{project_id}/files", dependencies=[READ],
            summary="List a project's files in upload order",
            responses=error_responses(ProjectNotFound, TagInvalid))
async def list_files(project_id: ProjectId, page: PaginationDep,
                     service: ProjectServiceDep, tag: TagQuery = None) -> FileListResponse:
    tag = clean_tags([tag])[0] if tag is not None else None
    result = await service.list_files(project_id, offset=page.offset, limit=page.limit, tag=tag)
    return FileListResponse(total=result.total, offset=result.offset, limit=result.limit,
                            items=[_file_response(record) for record in result.items])


@router.put("/{project_id}/files/{file_id}/tags", dependencies=[WRITE],
            summary="Replace a file's tags",
            description="Tags group files into collections: searches, answers and widgets "
                        "can be limited to files with some tags.",
            responses=error_responses(ProjectNotFound, FileNotFound))
async def set_file_tags(project_id: ProjectId, file_id: FileIdPath, request: FileTagsRequest,
                        service: TagServiceDep) -> FileResponse:
    return _file_response(await service.set_file_tags(project_id, file_id, request.tags))


@router.get("/{project_id}/tags", dependencies=[READ],
            summary="List a project's tags by name, with how many files have each",
            responses=error_responses(ProjectNotFound))
async def list_tags(project_id: ProjectId, service: TagServiceDep) -> TagListResponse:
    return TagListResponse(items=[TagResponse(tag=count.tag, files=count.files)
                                  for count in await service.list_tags(project_id)])


@router.get("/{project_id}/files/{file_id}/chunks", dependencies=[READ],
            summary="List a file's chunks in order",
            responses=error_responses(ProjectNotFound, FileNotFound))
async def list_chunks(project_id: ProjectId, file_id: FileIdPath, page: PaginationDep,
                      service: ProjectServiceDep) -> ChunkListResponse:
    result = await service.list_chunks(project_id, file_id, offset=page.offset, limit=page.limit)
    return ChunkListResponse(
        total=result.total, offset=result.offset, limit=result.limit,
        items=[ChunkResponse(chunk_index=chunk.index, text=chunk.text, metadata=chunk.metadata)
               for chunk in result.items])


@router.delete("/{project_id}", dependencies=[WRITE], status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a project with all its files, chunks, answers and conversations",
               responses=error_responses(ProjectNotFound))
async def delete_project(project_id: ProjectId, service: DeletionServiceDep) -> Response:
    await service.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{project_id}/files/{file_id}", dependencies=[WRITE],
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a file with its chunks",
               description="Answers that cited the file keep their copy of the cited text.",
               responses=error_responses(ProjectNotFound, FileNotFound))
async def delete_file(project_id: ProjectId, file_id: FileIdPath,
                      service: DeletionServiceDep) -> Response:
    await service.delete_file(project_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
