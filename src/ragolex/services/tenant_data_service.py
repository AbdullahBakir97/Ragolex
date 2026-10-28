"""Everything a tenant has: exported as one archive, or deleted for good.

The export is a ZIP archive a person can read and another system can
import. It holds what the tenant put in and what was recorded about it:

    manifest.json                       what is inside, and when it was made
    tenant.json                         the tenant and its limits
    api_keys.json                       names, prefixes and scopes; never keys or their hashes
    members.json                        the people with accounts in it, and their roles
    invitations.json                    invitations not accepted yet; never their links
    domains.json                        its own domains, and whether each is verified
    audit.jsonl                         the audit log, oldest first
    projects/<project>/project.json     the project, and its answer usage added up
    projects/<project>/files.json       each file's name, type, size, checksum and tags
    projects/<project>/files/<file_id>  the files themselves, as uploaded
    projects/<project>/sources.json     websites and other sources it syncs from
    projects/<project>/widgets.json     chat widgets
    projects/<project>/webhooks.json    webhooks, without their signing secrets
    projects/<project>/bots.json        Telegram, Slack and WhatsApp bots, without credentials
    projects/<project>/conversations.jsonl  questions and answers, with citations and feedback

Chunks and their embeddings are left out: processing the files again makes
them, with whichever model the importing side uses.
"""

import json
import logging
import zipfile
from collections.abc import AsyncIterator, Collection
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import IO, Any

from ragolex.core.errors import FileNotFound
from ragolex.domain.models import AuditEvent, Project, Tenant
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.deletion_service import DeletionService
from ragolex.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

FORMAT = "ragolex-export"
FORMAT_VERSION = 1
PAGE = 200
# Ids that mean something only inside this database, and secrets.
_INTERNAL = {"id", "tenant_id", "project_id", "storage_name", "tenant_name", "secret"}


@dataclass
class TenantExport:
    """What goes into the archive: entries in order, each text or a file on disk."""

    tenant: Tenant
    entries: list[tuple[str, str | Path]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    # Files the database lists that are no longer on disk.
    missing_files: list[str] = field(default_factory=list)
    # Where the files are stored, to put them in the archive as uploaded (decrypted).
    storage: FileStorage | None = None

    def add_json(self, name: str, value: Any) -> None:
        self.entries.append((name, json.dumps(value, indent=2, ensure_ascii=False,
                                              default=_json_value) + "\n"))

    def add_lines(self, name: str, values: list[Any]) -> None:
        self.entries.append((name, "".join(
            json.dumps(value, ensure_ascii=False, default=_json_value) + "\n" for value in values)))

    def write(self, target: IO[bytes], app_version: str) -> None:
        """Writes the archive to ``target``; blocking, so run it off the event loop."""
        manifest = {
            "format": FORMAT, "format_version": FORMAT_VERSION, "app_version": app_version,
            "tenant": self.tenant.name, "exported_at": datetime.now(UTC),
            "counts": self.counts, "missing_files": self.missing_files,
            "left_out": ["chunks and embeddings: process the files again to make them",
                         "API keys and webhook secrets: only their names and prefixes",
                         "passwords, sessions and invitation links"],
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2,
                                                         default=_json_value) + "\n")
            for name, content in self.entries:
                if isinstance(content, Path):
                    with (self.storage.plaintext(content) if self.storage
                          else nullcontext(content)) as plain:
                        archive.write(plain, name)
                else:
                    archive.writestr(name, content)


class TenantDataService:
    """Exports or deletes everything of the tenant the unit of work acts for."""

    def __init__(self, uow: UnitOfWork, storage: FileStorage):
        self.uow = uow
        self.storage = storage

    async def export(self, tenant: Tenant) -> TenantExport:
        """Gathers the tenant's data; ``TenantExport.write`` then makes the archive."""
        export = TenantExport(tenant, storage=self.storage)
        export.add_json("tenant.json", _plain(tenant))
        keys = await self.uow.api_keys.list_for_tenant(tenant.id)
        export.add_json("api_keys.json", [_plain(key, keep={"id"}) for key in keys])
        members = await self.uow.memberships.list_for_tenant(tenant.id)
        export.add_json("members.json", [
            {"email": m.user.email, "name": m.user.name, "role": m.role,
             "joined_at": m.joined_at, "last_login_at": m.user.last_login_at} for m in members])
        invitations = await self.uow.invitations.list_pending(tenant.id)
        export.add_json("invitations.json", [
            {"email": i.email, "role": i.role, "created_at": i.created_at,
             "expires_at": i.expires_at} for i in invitations])
        events = [event async for event in self._audit(tenant.id)]
        export.add_lines("audit.jsonl", [_plain(event, keep={"id"}) for event in reversed(events)])
        domains = await self.uow.domains.list_for_tenant(tenant.id)
        export.add_json("domains.json", [
            {"domain": d.domain, "created_at": d.created_at, "verified_at": d.verified_at}
            for d in domains])
        export.counts.update(api_keys=len(keys), members=len(members),
                             invitations=len(invitations), domains=len(domains),
                             audit_events=len(events))

        projects = [project async for project in self._projects()]
        export.counts["projects"] = len(projects)
        for project in projects:
            await self._export_project(project, export)
        return export

    async def _export_project(self, project: Project, export: TenantExport) -> None:
        folder = f"projects/{project.name}"
        usage = await self.uow.answers.totals_for_project(project.id)
        export.add_json(f"{folder}/project.json", {**_plain(project), "usage": asdict(usage)})

        files = []
        offset = 0
        while page := await self.uow.files.list_for_project(project.id, offset=offset,
                                                            limit=PAGE):
            files += page
            offset += len(page)
        listed = []
        for record in files:
            try:
                path = self.storage.get_file_path(project.folder, record.key)
            except FileNotFound:
                path = None
                export.missing_files.append(f"{project.name}/{record.key}")
            if path is not None:
                export.entries.append((f"{folder}/files/{record.key}", path))
            listed.append({"file_id": record.key, **_plain(record),
                           "path": f"files/{record.key}" if path else None})
        export.add_json(f"{folder}/files.json", listed)

        export.add_json(f"{folder}/sources.json",
                        [_plain(source, keep={"id"})
                         for source in await self.uow.sources.list_for_project(project.id)])
        export.add_json(f"{folder}/widgets.json",
                        [_plain(widget, keep={"id"})
                         for widget in await self.uow.widgets.list_for_project(project.id)])
        webhooks = await self.uow.webhooks.list_for_project(project.id, offset=0, limit=1000)
        export.add_json(f"{folder}/webhooks.json",
                        [_plain(webhook, keep={"id"}) for webhook in webhooks])
        export.add_json(f"{folder}/bots.json", [
            {"id": bot.id, "kind": bot.kind, "name": bot.name, "account": bot.account,
             "tags": list(bot.tags), "enabled": bot.enabled, "created_at": bot.created_at}
            for bot in await self.uow.bots.list_for_project(project.id)])

        conversations = []
        offset = 0
        while chats := await self.uow.conversations.list_for_project(project.id, offset=offset,
                                                                     limit=PAGE):
            for conversation in chats:
                messages = await self.uow.conversations.messages(conversation.id)
                conversations.append({**_plain(conversation, keep={"id"}),
                                      "messages": [_plain(m) for m in messages]})
            offset += len(chats)
        export.add_lines(f"{folder}/conversations.jsonl", conversations)

        for name, count in (("files", len(files)), ("conversations", len(conversations))):
            export.counts[name] = export.counts.get(name, 0) + count

    async def delete(self, tenant: Tenant) -> int:
        """Deletes the tenant with all its projects, files on disk, keys and audit log.

        Each project goes with its files first, as when it is deleted on its
        own; the tenant row last, which takes its keys and audit log along.
        Run again after a failure, it carries on where it stopped. Returns
        how many projects were deleted.
        """
        deleted = 0
        while projects := await self.uow.projects.list_all(offset=0, limit=PAGE):
            for project in projects:
                await DeletionService(self.uow, self.storage).delete_project(project.name)
                deleted += 1
        await self.uow.tenants.delete(tenant.id)
        await self.uow.commit()
        logger.info("Tenant %s was deleted with its %d projects.", tenant.name, deleted)
        return deleted

    async def _projects(self) -> AsyncIterator[Project]:
        offset = 0
        while page := await self.uow.projects.list_all(offset=offset, limit=PAGE):
            for project in page:
                yield project
            offset += len(page)

    async def _audit(self, tenant_id: int) -> AsyncIterator[AuditEvent]:
        offset = 0
        while page := await self.uow.audit.list_for_tenant(tenant_id, action=None,
                                                           offset=offset, limit=PAGE):
            for event in page:
                yield event
            offset += len(page)


def _plain(record: Any, keep: Collection[str] = ()) -> dict[str, Any]:
    """A record as JSON-ready fields, without database ids (unless kept) and secrets."""
    return {name: value for name, value in asdict(record).items()
            if name not in _INTERNAL - set(keep)}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot export {type(value).__name__}")
