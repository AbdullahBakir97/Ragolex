"""Gauges read from the database when /metrics is scraped: the work that is waiting."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .tables import JobRow, WebhookDeliveryRow


async def queue_depths(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Jobs by status and webhook deliveries by status, across every tenant."""
    jobs = await session.execute(select(JobRow.status, func.count()).group_by(JobRow.status))
    deliveries = await session.execute(
        select(WebhookDeliveryRow.status, func.count()).group_by(WebhookDeliveryRow.status))
    return {"jobs": {status: count for status, count in jobs},
            "webhook_deliveries": {status: count for status, count in deliveries}}
