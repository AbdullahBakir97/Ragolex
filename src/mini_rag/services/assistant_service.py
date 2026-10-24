from collections.abc import Mapping
from typing import Any

from mini_rag.core.errors import ProjectNotFound
from mini_rag.domain.models import Project
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.services.audit import record


class AssistantService:
    """The assistant that answers from a project: its name and its owner's instructions."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def get(self, project_name: str) -> Project:
        project = await self.uow.projects.get_by_name(project_name)
        if project is None:
            raise ProjectNotFound()
        return project

    async def update(self, project_name: str, changes: Mapping[str, Any]) -> Project:
        """Change ``assistant_name`` and ``instructions``, those in ``changes`` only.

        Blank values clear them: the assistant then has no name of its own,
        or no instructions beyond the answer rules.
        """
        project = await self.get(project_name)
        name = _text(changes["assistant_name"]) if "assistant_name" in changes \
            else project.assistant_name
        instructions = _text(changes["instructions"]) if "instructions" in changes \
            else project.instructions
        updated = await self.uow.projects.set_assistant(project.id, assistant_name=name,
                                                        instructions=instructions)
        await record(self.uow, project.tenant_id, "project.assistant_updated", project.name,
                     assistant_name=name, instructions=instructions)
        await self.uow.commit()
        return updated


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None
