from collections.abc import Iterable

from ragolex.core.errors import FileNotFound, ProjectNotFound, TagInvalid
from ragolex.domain.models import FileRecord, Project, TagCount
from ragolex.domain.repositories import UnitOfWork
from ragolex.domain.tags import MAX_TAGS_PER_FILE, InvalidTag, normalize_tags


def clean_tags(tags: Iterable[str], *, limit: int | None = MAX_TAGS_PER_FILE) -> tuple[str, ...]:
    """Normalized tags without duplicates (see domain.tags); TagInvalid for a bad one."""
    try:
        return normalize_tags(tags, limit=limit)
    except InvalidTag as exc:
        raise TagInvalid(str(exc)) from None


def split_tags(text: str | None) -> tuple[str, ...]:
    """Tags from a comma-separated list, as an upload form sends them."""
    return clean_tags(tag for tag in (text or "").split(",") if tag.strip())


class TagService:
    """Tags group a project's files into collections."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def set_file_tags(self, project_name: str, file_key: str,
                            tags: Iterable[str]) -> FileRecord:
        """Replace a file's tags."""
        project = await self._project(project_name)
        record = await self.uow.files.set_tags(project.id, file_key, clean_tags(tags))
        if record is None:
            raise FileNotFound()
        await self.uow.commit()
        return record

    async def list_tags(self, project_name: str) -> list[TagCount]:
        """The project's tags by name, each with how many files have it."""
        project = await self._project(project_name)
        return await self.uow.files.tag_counts(project.id)

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
