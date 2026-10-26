from typing import Annotated

from fastapi import APIRouter, Form, UploadFile

from ragolex.api.dependencies import WRITE, ProcessingServiceDep, UploadServiceDep
from ragolex.api.schemas import (
    TAGS_DESCRIPTION,
    ProcessRequest,
    ProcessResponse,
    ProjectId,
    UploadResponse,
    error_responses,
)
from ragolex.core.errors import (
    FileNotFound,
    FileTooLarge,
    NoTextExtracted,
    OcrFailed,
    ProcessingFailed,
    TagInvalid,
    UnsupportedFileType,
    UploadFailed,
)
from ragolex.domain.signals import ResponseSignal
from ragolex.services.tag_service import split_tags

router = APIRouter(prefix="/api/v1/data", tags=["data"], dependencies=[WRITE])


@router.post(
    "/upload/{project_id}",
    summary="Upload a file into a project",
    description="Content the project already has is not stored again: the response then has "
                "signal `file_already_uploaded` and the existing file's id, so uploading "
                "the same files again is safe; a duplicate gains the tags it did not have.",
    responses=error_responses(UnsupportedFileType, FileTooLarge, TagInvalid, UploadFailed),
)
async def upload_data(
    project_id: ProjectId, file: UploadFile, upload_service: UploadServiceDep,
    tags: Annotated[str | None, Form(max_length=1000,
                                     description="Comma-separated. " + TAGS_DESCRIPTION)] = None,
) -> UploadResponse:
    upload = await upload_service.save(
        project_name=project_id,
        filename=file.filename or "",
        content_type=file.content_type,
        stream=file,
        declared_size=file.size,
        tags=split_tags(tags),
    )
    signal = (ResponseSignal.FILE_ALREADY_UPLOADED if upload.duplicate
              else ResponseSignal.FILE_UPLOAD_SUCCESS)
    return UploadResponse(signal=signal, file_id=upload.file_id)


@router.post(
    "/process/{project_id}",
    summary="Split an uploaded file into chunks and store them",
    description="Processing a file again replaces its previous chunks. "
                "Read the chunks with GET /api/v1/projects/{project_id}/files/{file_id}/chunks.",
    responses=error_responses(FileNotFound, UnsupportedFileType, NoTextExtracted, ProcessingFailed,
                              OcrFailed),
)
async def process_data(project_id: ProjectId, request: ProcessRequest,
                       processing_service: ProcessingServiceDep) -> ProcessResponse:
    chunks_count = await processing_service.process(
        project_name=project_id,
        file_key=request.file_id,
        chunk_size=request.chunk_size,
        overlap_size=request.overlap_size,
    )
    return ProcessResponse(
        signal=ResponseSignal.PROCESSING_SUCCESS,
        file_id=request.file_id,
        chunks_count=chunks_count,
    )
