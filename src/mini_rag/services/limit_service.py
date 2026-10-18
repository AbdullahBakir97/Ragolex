import logging
import math
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

from mini_rag.core.errors import (
    AnswerQuotaExceeded,
    BudgetExceeded,
    RateLimited,
    StorageQuotaExceeded,
)
from mini_rag.core.metrics import BUDGET_ALERTS
from mini_rag.domain.models import Limits, Project, TenantUsage, UsageHistory
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.services.audit import record
from mini_rag.services.webhook_service import envelope

logger = logging.getLogger(__name__)

BYTES_PER_MB = 1024 * 1024
# Percents of the monthly budget that send an alert, once each per month.
BUDGET_ALERT_THRESHOLDS = (80, 100)


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
        """Refuse an answer once the tenant's answers this month reach its quota or budget."""
        limits = await self.limits_for(tenant_id)
        if not (limits.answers_per_month or limits.budget_usd_per_month):
            return
        used = await self.uow.usage.tenant_usage(tenant_id)
        if limits.answers_per_month and used.answers >= limits.answers_per_month:
            raise AnswerQuotaExceeded(f"All {limits.answers_per_month} answers of this month "
                                      "are used")
        if limits.budget_usd_per_month and used.cost_usd >= limits.budget_usd_per_month:
            raise BudgetExceeded(f"This month's budget of ${limits.budget_usd_per_month:,.2f} "
                                 "is spent")

    async def note_spending(self, project: Project) -> list[int]:
        """Alert about the budget thresholds the tenant's spending this month has reached.

        Called after an answer is recorded, in its transaction. Each threshold
        is announced once a month: a ``budget.alert`` webhook event to the
        tenant's webhooks that subscribe to it, an audit event and a warning
        in the log. Returns the thresholds announced now.
        """
        budget = (await self.limits_for(project.tenant_id)).budget_usd_per_month
        if not budget:
            return []
        used = await self.uow.usage.tenant_usage(project.tenant_id)
        reached = [threshold for threshold in BUDGET_ALERT_THRESHOLDS
                   if used.cost_usd >= budget * threshold / 100
                   and await self.uow.usage.add_budget_alert(project.tenant_id, threshold)]
        for threshold in reached:
            details = {"threshold_percent": threshold, "budget_usd": budget,
                       "cost_usd": round(used.cost_usd, 6),
                       "period_start": used.period_start.isoformat()}
            await self.uow.webhooks.enqueue_for_tenant(
                project.tenant_id, "budget.alert", envelope(project, "budget.alert", details))
            await record(self.uow, project.tenant_id, "budget.alert", None, **details)
            logger.warning("Budget alert: the tenant's answers cost %s this month, %d%% of its "
                           "%s budget", _dollars(used.cost_usd), threshold, _dollars(budget))
            BUDGET_ALERTS.labels(threshold=str(threshold)).inc()
        return reached

    async def history(self, tenant_id: int, days: int) -> UsageHistory:
        return await self.uow.usage.history(tenant_id, days)

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


def _dollars(amount: float) -> str:
    return f"${amount:,.2f}" if amount >= 1 else f"${amount:.4g}"


def _now(like: datetime) -> datetime:
    return datetime.now(like.tzinfo)


def check_storage(left: int | None, size: int) -> None:
    """Raise StorageQuotaExceeded when ``size`` more bytes do not fit in ``left``."""
    if left is not None and size > left:
        raise StorageQuotaExceeded("The upload does not fit in the tenant's storage")
