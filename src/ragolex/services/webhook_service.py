import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ragolex.core.errors import ProjectNotFound, WebhookNotFound, WebhookUrlNotAllowed
from ragolex.core.network import is_local_host
from ragolex.domain.models import Project, Webhook, WebhookDelivery
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record


async def emit(uow: UnitOfWork, project: Project, event: str, data: Mapping[str, Any]) -> None:
    """Queue ``event`` for the project's webhooks, in the caller's transaction.

    Every delivery carries the same envelope: the event, when it happened,
    the project, and the event's ``data``.
    """
    await uow.webhooks.enqueue(project.id, event, envelope(project, event, data))


def envelope(project: Project, event: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """What a delivery of ``event`` carries."""
    return {"event": event, "created_at": datetime.now(UTC).isoformat(),
            "project": project.name, "data": dict(data)}


@dataclass(frozen=True)
class WebhookPage:
    items: list[Webhook]
    total: int


@dataclass(frozen=True)
class DeliveryPage:
    items: list[WebhookDelivery]
    total: int


class WebhookService:
    """Adds and removes a project's webhooks, and shows what was sent to them."""

    def __init__(self, uow: UnitOfWork, allow_private_urls: bool):
        self.uow = uow
        self.allow_private_urls = allow_private_urls

    async def create(self, project_name: str, url: str, events: Sequence[str],
                     description: str | None) -> Webhook:
        """Add a webhook with a new secret. The project is created if it has no files yet."""
        host = urlsplit(url).hostname or ""
        if not self.allow_private_urls and is_local_host(host):
            raise WebhookUrlNotAllowed()
        project = await self.uow.projects.get_or_create(project_name)
        webhook = await self.uow.webhooks.create(
            project_id=project.id, url=url, events=sorted(set(events)),
            secret="whsec_" + secrets.token_urlsafe(32), description=description)
        await record(self.uow, project.tenant_id, "webhook.created", webhook.id,
                     project=project.name, url=webhook.url, events=list(webhook.events))
        await self.uow.commit()
        return webhook

    async def get(self, project_name: str, webhook_id: str) -> Webhook:
        project = await self._project(project_name)
        webhook = await self.uow.webhooks.get(project.id, webhook_id)
        if webhook is None:
            raise WebhookNotFound()
        return webhook

    async def list(self, project_name: str, *, offset: int, limit: int) -> WebhookPage:
        project = await self._project(project_name)
        items = await self.uow.webhooks.list_for_project(project.id, offset=offset, limit=limit)
        return WebhookPage(items=items, total=await self.uow.webhooks.count_for_project(project.id))

    async def delete(self, project_name: str, webhook_id: str) -> None:
        project = await self._project(project_name)
        if not await self.uow.webhooks.delete(project.id, webhook_id):
            raise WebhookNotFound()
        await record(self.uow, project.tenant_id, "webhook.deleted", webhook_id,
                     project=project.name)
        await self.uow.commit()

    async def ping(self, project_name: str, webhook_id: str) -> WebhookDelivery:
        """Queue a ``ping`` event to the webhook, to check that it is reached."""
        webhook = await self.get(project_name, webhook_id)
        delivery = await self.uow.webhooks.add_delivery(webhook.id, "ping", {
            "event": "ping", "created_at": datetime.now(UTC).isoformat(),
            "project": project_name, "data": {"webhook_id": webhook.id}})
        await self.uow.commit()
        return delivery

    async def deliveries(self, project_name: str, webhook_id: str, *, offset: int,
                         limit: int) -> DeliveryPage:
        webhook = await self.get(project_name, webhook_id)
        items = await self.uow.webhooks.list_deliveries(webhook.id, offset=offset, limit=limit)
        return DeliveryPage(items=items, total=await self.uow.webhooks.count_deliveries(webhook.id))

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
