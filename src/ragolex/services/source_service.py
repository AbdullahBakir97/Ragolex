from collections.abc import Sequence
from urllib.parse import urlsplit

from ragolex.core.errors import (
    FileNotFound,
    ProjectNotFound,
    SourceNotFound,
    SourceUrlNotAllowed,
)
from ragolex.core.network import is_local_host
from ragolex.domain.models import Project, Source, SourcePage
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record
from ragolex.services.deletion_service import DeletionService
from ragolex.services.tag_service import clean_tags
from ragolex.storage.file_storage import FileStorage


class SourceService:
    """Adds, lists and removes a project's sources; a SourceSyncer keeps them in sync."""

    def __init__(self, uow: UnitOfWork, storage: FileStorage, allow_private_urls: bool):
        self.uow = uow
        self.storage = storage
        self.allow_private_urls = allow_private_urls

    async def create(self, project_name: str, url: str, max_pages: int,
                     sync_interval_hours: int, tags: Sequence[str] = ()) -> Source:
        """Add a website, synced at once; the project is created if it has no files yet.

        Its pages get ``tags``.
        """
        host = urlsplit(url).hostname or ""
        if not self.allow_private_urls and is_local_host(host):
            raise SourceUrlNotAllowed()
        project = await self.uow.projects.get_or_create(project_name)
        source = await self.uow.sources.create(project_id=project.id, kind="website", url=url,
                                               max_pages=max_pages,
                                               sync_interval_hours=sync_interval_hours,
                                               tags=clean_tags(tags))
        await record(self.uow, project.tenant_id, "source.created", source.id,
                     project=project.name, url=url, max_pages=max_pages,
                     sync_interval_hours=sync_interval_hours, tags=list(source.tags))
        await self.uow.commit()
        return source

    async def list(self, project_name: str) -> list[Source]:
        project = await self._project(project_name)
        return await self.uow.sources.list_for_project(project.id)

    async def get(self, project_name: str, source_id: str) -> Source:
        project = await self._project(project_name)
        source = await self.uow.sources.get(project.id, source_id)
        if source is None:
            raise SourceNotFound()
        return source

    async def pages(self, project_name: str, source_id: str, *, offset: int,
                    limit: int) -> tuple[Source, Sequence[SourcePage]]:
        source = await self.get(project_name, source_id)
        return source, await self.uow.sources.pages(source.id, offset=offset, limit=limit)

    async def sync(self, project_name: str, source_id: str) -> Source:
        """Sync the source as soon as a worker is free."""
        source = await self.get(project_name, source_id)
        await self.uow.sources.request_sync(source.id)
        await self.uow.commit()
        return await self.get(project_name, source_id)

    async def delete(self, project_name: str, source_id: str, *, keep_files: bool) -> None:
        """Remove the source, and unless ``keep_files`` the files its syncs stored."""
        source = await self.get(project_name, source_id)
        pages = [] if keep_files else await self.uow.sources.pages(source.id)
        await self.uow.sources.delete(source.project_id, source.id)
        await record(self.uow, source.tenant_id, "source.deleted", source.id,
                     project=source.project_name, url=source.url, kept_files=keep_files)
        await self.uow.commit()
        deletion = DeletionService(self.uow, self.storage)
        for page in pages:
            if page.owns_file and not await self.uow.sources.file_used_elsewhere(
                    page.file_id, source.id, page.url):
                try:
                    await deletion.delete_file(source.project_name, page.file_key)
                except FileNotFound:
                    pass  # Deleted by hand already.

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
