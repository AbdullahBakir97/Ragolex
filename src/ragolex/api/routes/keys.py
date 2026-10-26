from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from ragolex.api.dependencies import (
    ADMIN,
    READ,
    AuthServiceDep,
    LimitServiceDep,
    PrincipalDep,
    SettingsDep,
)
from ragolex.api.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyRequest,
    ApiKeyResponse,
    DayUsageResponse,
    KeyIdPath,
    MeResponse,
    Meter,
    ModelShareResponse,
    ProjectShareResponse,
    TenantUsageResponse,
    UsageHistoryResponse,
    error_responses,
)
from ragolex.core.errors import ApiKeyNotFound
from ragolex.domain.models import ApiKey
from ragolex.services.limit_service import BYTES_PER_MB

router = APIRouter(prefix="/api/v1", tags=["keys"])


def _key(key: ApiKey) -> dict:
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "scopes": list(key.scopes),
            "created_at": key.created_at, "last_used_at": key.last_used_at,
            "revoked_at": key.revoked_at}


@router.get("/me", summary="The tenant and scopes of the API key used")
async def me(principal: PrincipalDep, settings: SettingsDep) -> MeResponse:
    return MeResponse(tenant=principal.tenant_name, scopes=sorted(principal.scopes),
                      key_id=principal.key_id, auth_enabled=settings.AUTH_ENABLED)


@router.get("/keys", dependencies=[ADMIN], summary="The tenant's API keys, newest first")
async def list_keys(principal: PrincipalDep, service: AuthServiceDep) -> list[ApiKeyResponse]:
    return [ApiKeyResponse(**_key(key)) for key in await service.list_keys(principal.tenant_id)]


@router.post("/keys", dependencies=[ADMIN], status_code=status.HTTP_201_CREATED,
             summary="Create an API key for the tenant",
             description="The key is returned only once; only a hash of it is stored.")
async def create_key(request: ApiKeyRequest, principal: PrincipalDep,
                     service: AuthServiceDep) -> ApiKeyCreatedResponse:
    record, key = await service.create_key(principal.tenant_id, request.name, request.scopes)
    return ApiKeyCreatedResponse(**_key(record), key=key)


@router.delete("/keys/{key_id}", dependencies=[ADMIN], status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke an API key", description="It stops working at once.",
               responses=error_responses(ApiKeyNotFound))
async def revoke_key(key_id: KeyIdPath, principal: PrincipalDep,
                     service: AuthServiceDep) -> Response:
    await service.revoke_key(principal.tenant_id, str(key_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usage", dependencies=[READ], summary="The tenant's usage this month, and its limits")
async def usage(principal: PrincipalDep, limits: LimitServiceDep) -> TenantUsageResponse:
    used, limit = await limits.usage(principal.tenant_id)
    return TenantUsageResponse(
        tenant=principal.tenant_name, period_start=used.period_start,
        requests_per_minute=limit.requests_per_minute or None,
        answers=Meter(used=used.answers, limit=limit.answers_per_month or None),
        storage_bytes=Meter(used=used.storage_bytes,
                            limit=limit.storage_mb * BYTES_PER_MB if limit.storage_mb else None),
        input_tokens=used.input_tokens, output_tokens=used.output_tokens,
        cost_usd=used.cost_usd, budget_usd=limit.budget_usd_per_month or None)


@router.get("/usage/history", dependencies=[READ],
            summary="The tenant's answers and their cost per day, project and model",
            description="Over the last `days` days (UTC), today included: for a cost "
                        "dashboard. Costs are those known, as in `/usage`.")
async def usage_history(principal: PrincipalDep, limits: LimitServiceDep,
                        days: Annotated[int, Query(ge=1, le=366)] = 30,
                        ) -> UsageHistoryResponse:
    history = await limits.history(principal.tenant_id, days)

    def counts(total):
        return {"answers": total.answers, "input_tokens": total.input_tokens,
                "output_tokens": total.output_tokens, "cost_usd": total.cost_usd}

    return UsageHistoryResponse(
        start=history.start,
        days=[DayUsageResponse(day=date.fromisoformat(str(total.key)), **counts(total)) for total in history.days],
        projects=[ProjectShareResponse(project=str(total.key), **counts(total))
                  for total in history.projects],
        models=[ModelShareResponse(model=total.key, **counts(total)) for total in history.models])

