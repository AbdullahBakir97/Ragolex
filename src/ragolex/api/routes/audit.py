from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ragolex.api.dependencies import ADMIN, PrincipalDep, UnitOfWorkDep
from ragolex.api.schemas import (
    AuditActor,
    AuditEventResponse,
    AuditListResponse,
    Pagination,
)
from ragolex.domain.models import AuditEvent
from ragolex.services.audit import AuditService

router = APIRouter(prefix="/api/v1", tags=["audit"], dependencies=[ADMIN])


def _event(event: AuditEvent) -> AuditEventResponse:
    actor = (AuditActor(key_id=event.actor_key_id, name=event.actor_key_name)
             if event.actor_key_id else None)
    return AuditEventResponse(id=event.id, action=event.action, target=event.target,
                              details=event.details, actor=actor, request_id=event.request_id,
                              created_at=event.created_at)


@router.get(
    "/audit",
    summary="The tenant's audit log, most recent first",
    description="Administrative actions: API keys created and revoked, webhooks and chat "
                "widgets added, changed and removed, files and projects deleted, and limits "
                "changed, each with the key that did it and its request id. Kept as long as "
                "the tenant.",
)
async def list_audit_events(
    principal: PrincipalDep, uow: UnitOfWorkDep, page: Annotated[Pagination, Depends()],
    action: Annotated[str | None, Query(
        max_length=64, description="Only actions that start with this, e.g. `api_key` or "
                                   "`widget.deleted`.")] = None,
) -> AuditListResponse:
    result = await AuditService(uow).list(principal.tenant_id, action=action,
                                          offset=page.offset, limit=page.limit)
    return AuditListResponse(total=result.total, offset=result.offset, limit=result.limit,
                             items=[_event(event) for event in result.items])
