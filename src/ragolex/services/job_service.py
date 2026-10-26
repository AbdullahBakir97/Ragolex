from dataclasses import dataclass

from ragolex.core.errors import (
    FileNotFound,
    JobNotFailed,
    JobNotFound,
    ProjectNotFound,
)
from ragolex.domain.models import Job, JobStatus, Project
from ragolex.domain.repositories import UnitOfWork


@dataclass(frozen=True)
class JobPage:
    items: list[Job]
    total: int


class JobService:
    """Queues files to be processed and indexed in the background, and reports on them.

    A worker (``JobRunner``) does the work; this only records what to do.
    """

    def __init__(self, uow: UnitOfWork, max_attempts: int):
        self.uow = uow
        self.max_attempts = max_attempts

    async def enqueue(self, project_name: str, file_key: str, chunk_size: int,
                      overlap_size: int) -> Job:
        project = await self._project(project_name)
        record = await self.uow.files.get_by_key(project.id, file_key)
        if record is None:
            raise FileNotFound()
        job = await self.uow.jobs.add(project_id=project.id, file_id=record.id,
                                      chunk_size=chunk_size, overlap_size=overlap_size,
                                      max_attempts=self.max_attempts)
        await self.uow.commit()
        return job

    async def get(self, project_name: str, job_id: str) -> Job:
        project = await self._project(project_name)
        job = await self.uow.jobs.get(project.id, job_id)
        if job is None:
            raise JobNotFound()
        return job

    async def list(self, project_name: str, *, status: JobStatus | None, offset: int,
                   limit: int) -> JobPage:
        project = await self._project(project_name)
        items = await self.uow.jobs.list_for_project(project.id, status=status, offset=offset,
                                                     limit=limit)
        total = await self.uow.jobs.count_for_project(project.id, status=status)
        return JobPage(items=items, total=total)

    async def retry(self, project_name: str, job_id: str) -> Job:
        """Queue a failed job again, with all its attempts."""
        job = await self.get(project_name, job_id)
        if job.status != "failed":
            raise JobNotFailed()
        await self.uow.jobs.requeue(job.id)
        await self.uow.commit()
        return await self.get(project_name, job_id)

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
