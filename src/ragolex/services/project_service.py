from dataclasses import dataclass
from typing import Generic, TypeVar

from ragolex.core.errors import FileNotFound, ProjectNotFound
from ragolex.domain.models import Chunk, FileRecord, Project, UsageTotals
from ragolex.domain.repositories import UnitOfWork


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    files_count: int
    chunks_count: int
    embedded_chunks_count: int


T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class ProjectService:
    """Read-only queries about projects, their files and their chunks."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def list_projects(self, offset: int, limit: int) -> Page[Project]:
        """Projects in name order. A project exists once a file was uploaded into it."""
        return Page(
            items=await self.uow.projects.list_all(offset=offset, limit=limit),
            total=await self.uow.projects.count(),
            offset=offset, limit=limit,
        )

    async def get_summary(self, project_name: str) -> ProjectSummary:
        project = await self._project(project_name)
        return ProjectSummary(
            project=project,
            files_count=await self.uow.files.count_for_project(project.id),
            chunks_count=await self.uow.chunks.count_for_project(project.id),
            embedded_chunks_count=await self.uow.chunks.count_embedded_for_project(project.id),
        )

    async def list_files(self, project_name: str, offset: int, limit: int,
                         tag: str | None = None) -> Page[FileRecord]:
        """Files in upload order; ``tag`` keeps those that have it."""
        project = await self._project(project_name)
        return Page(
            items=await self.uow.files.list_for_project(project.id, offset=offset, limit=limit,
                                                        tag=tag),
            total=await self.uow.files.count_for_project(project.id, tag=tag),
            offset=offset, limit=limit,
        )

    async def list_chunks(self, project_name: str, file_key: str,
                          offset: int, limit: int) -> Page[Chunk]:
        project = await self._project(project_name)
        record = await self.uow.files.get_by_key(project.id, file_key)
        if record is None:
            raise FileNotFound()
        return Page(
            items=await self.uow.chunks.list_for_file(record.id, offset=offset, limit=limit),
            total=await self.uow.chunks.count_for_file(record.id),
            offset=offset, limit=limit,
        )

    async def get_usage(self, project_name: str) -> UsageTotals:
        """Token usage and cost of all the project's answers."""
        project = await self._project(project_name)
        return await self.uow.answers.totals_for_project(project.id)

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
