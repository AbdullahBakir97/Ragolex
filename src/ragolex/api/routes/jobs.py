from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from ragolex.api.dependencies import READ, WRITE, JobServiceDep
from ragolex.api.schemas import (
    JobIdPath,
    JobListResponse,
    JobRequest,
    JobResponse,
    Pagination,
    ProjectId,
    error_responses,
)
from ragolex.core.errors import (
    FileNotFound,
    JobNotFailed,
    JobNotFound,
    ProjectNotFound,
)
from ragolex.domain.models import Job

router = APIRouter(prefix="/api/v1/projects", tags=["jobs"])

PaginationDep = Annotated[Pagination, Depends()]


def _job(job: Job) -> JobResponse:
    return JobResponse(id=job.id, file_id=job.file_key, status=job.status, stage=job.stage,
                       progress=job.progress, chunks_count=job.chunks_count,
                       attempts=job.attempts, max_attempts=job.max_attempts,
                       chunk_size=job.chunk_size, overlap_size=job.overlap_size,
                       error=job.error_signal, created_at=job.created_at,
                       started_at=job.started_at, finished_at=job.finished_at)


@router.post("/{project_id}/jobs", dependencies=[WRITE], status_code=status.HTTP_202_ACCEPTED,
             summary="Process and index a file in the background",
             description="The same work as POST /data/process and POST /index, done by a "
                         "worker. Follow it with GET .../jobs/{job_id}.",
             responses=error_responses(ProjectNotFound, FileNotFound))
async def create_job(project_id: ProjectId, request: JobRequest,
                     service: JobServiceDep) -> JobResponse:
    return _job(await service.enqueue(project_id, request.file_id, request.chunk_size,
                                      request.overlap_size))


@router.get("/{project_id}/jobs", dependencies=[READ], summary="List jobs, most recent first",
            responses=error_responses(ProjectNotFound))
async def list_jobs(project_id: ProjectId, page: PaginationDep, service: JobServiceDep,
                    status_filter: Annotated[
                        Literal["queued", "running", "succeeded", "failed"] | None,
                        Query(alias="status", description="Only jobs with this status.")] = None,
                    ) -> JobListResponse:
    result = await service.list(project_id, status=status_filter, offset=page.offset,
                                limit=page.limit)
    return JobListResponse(total=result.total, offset=page.offset, limit=page.limit,
                           items=[_job(job) for job in result.items])


@router.get("/{project_id}/jobs/{job_id}", dependencies=[READ],
            summary="A job's status and progress",
            responses=error_responses(ProjectNotFound, JobNotFound))
async def get_job(project_id: ProjectId, job_id: JobIdPath,
                  service: JobServiceDep) -> JobResponse:
    return _job(await service.get(project_id, str(job_id)))


@router.post("/{project_id}/jobs/{job_id}/retry", dependencies=[WRITE],
             status_code=status.HTTP_202_ACCEPTED,
             summary="Queue a failed job again",
             responses=error_responses(ProjectNotFound, JobNotFound, JobNotFailed))
async def retry_job(project_id: ProjectId, job_id: JobIdPath,
                    service: JobServiceDep) -> JobResponse:
    return _job(await service.retry(project_id, str(job_id)))
