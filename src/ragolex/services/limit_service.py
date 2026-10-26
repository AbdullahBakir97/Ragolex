import math
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

from ragolex.core.errors import AnswerQuotaExceeded, RateLimited, StorageQuotaExceeded
from ragolex.domain.models import Limits, TenantUsage
from ragolex.domain.repositories import UnitOfWork

BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class RateState:
    """A tenant's rate limit after a request: for the X-RateLimit-* headers."""

    limit: int
    remaining: int
    reset_at: datetime


class LimitService:
    """Enforces each tenant's rate limit and quotas.

    A tenant's own limits override the server's ``defaults``; 0 is unlimited.
    """

    def __init__(self, uow: UnitOfWork, defaults: Limits):
        self.uow = uow
        self.defaults = defaults

    async def limits_for(self, tenant_id: int) -> Limits:
        tenant = await self.uow.tenants.get_by_id(tenant_id)
        return Limits(**{
            field.name: value if (value := getattr(tenant, field.name, None)) is not None
            else getattr(self.defaults, field.name)
            for field in fields(Limits)})

    async def count_request(self, tenant_id: int) -> RateState | None:
        """Count a request against the tenant's rate limit; None when it has none.

        Requests are counted per minute of the clock, across every API process.
        """
        limit = (await self.limits_for(tenant_id)).requests_per_minute
        if not limit:
            return None
        count, window_start = await self.uow.usage.count_request(tenant_id)
        await self.uow.commit()
        reset_at = window_start + timedelta(minutes=1)
        if count > limit:
            wait = max(1, math.ceil((reset_at - _now(window_start)).total_seconds()))
            raise RateLimited(f"More than {limit} requests this minute", headers={
                "Retry-After": str(wait), **_headers(RateState(limit, 0, reset_at))})
        return RateState(limit, limit - count, reset_at)

    async def check_answers(self, tenant_id: int) -> None:
        """Refuse an answer once the tenant's answers this month reach its quota."""
        quota = (await self.limits_for(tenant_id)).answers_per_month
        if quota and (await self.uow.usage.tenant_usage(tenant_id)).answers >= quota:
            raise AnswerQuotaExceeded(f"All {quota} answers of this month are used")

    async def storage_left(self, tenant_id: int) -> int | None:
        """Bytes the tenant may still upload; None when unlimited."""
        megabytes = (await self.limits_for(tenant_id)).storage_mb
        if not megabytes:
            return None
        used = (await self.uow.usage.tenant_usage(tenant_id)).storage_bytes
        return max(0, megabytes * BYTES_PER_MB - used)

    async def usage(self, tenant_id: int) -> tuple[TenantUsage, Limits]:
        return await self.uow.usage.tenant_usage(tenant_id), await self.limits_for(tenant_id)


def rate_headers(state: RateState | None) -> dict[str, str]:
    return _headers(state) if state else {}


def _headers(state: RateState) -> dict[str, str]:
    return {"X-RateLimit-Limit": str(state.limit),
            "X-RateLimit-Remaining": str(state.remaining),
            "X-RateLimit-Reset": str(int(state.reset_at.timestamp()))}


def _now(like: datetime) -> datetime:
    return datetime.now(like.tzinfo)


def check_storage(left: int | None, size: int) -> None:
    """Raise StorageQuotaExceeded when ``size`` more bytes do not fit in ``left``."""
    if left is not None and size > left:
        raise StorageQuotaExceeded("The upload does not fit in the tenant's storage")
