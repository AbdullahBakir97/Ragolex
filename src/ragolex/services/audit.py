from typing import Any

from ragolex.core import log_context
from ragolex.domain.models import AuditEvent
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.project_service import Page


async def record(uow: UnitOfWork, tenant_id: int, action: str, target: str | None = None,
                 **details: Any) -> None:
    """Note an administrative action in the tenant's audit log, in the caller's transaction.

    The event names the API key and the request it came from, so it is
    saved exactly when the action is, with who did it.
    """
    await uow.audit.add(tenant_id=tenant_id, action=action, target=target, details=details,
                        actor_key_id=log_context.actor.get(),
                        request_id=log_context.request_id.get())


class AuditService:
    """Reads a tenant's audit log."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def list(self, tenant_id: int, *, action: str | None, offset: int,
                   limit: int) -> Page[AuditEvent]:
        return Page(
            items=await self.uow.audit.list_for_tenant(tenant_id, action=action, offset=offset,
                                                       limit=limit),
            total=await self.uow.audit.count_for_tenant(tenant_id, action=action),
            offset=offset, limit=limit)
