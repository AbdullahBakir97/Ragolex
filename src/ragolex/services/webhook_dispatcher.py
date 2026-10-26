import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from ragolex.core.errors import WebhookFailed
from ragolex.core.log_context import log_context
from ragolex.core.metrics import WEBHOOK_DELIVERIES
from ragolex.domain.models import Webhook, WebhookDelivery
from ragolex.domain.repositories import UnitOfWork
from ragolex.domain.webhook_sender import WebhookSender

logger = logging.getLogger(__name__)

# Waits between attempts: 8 attempts over about 20 hours.
RETRY_DELAYS = (10, 60, 300, 1800, 7200, 21600, 43200)


def signature(secret: str, timestamp: int, body: bytes) -> str:
    """The ``X-Ragolex-Signature`` header: ``t=<timestamp>,v1=<hex HMAC-SHA256>``.

    The HMAC covers ``<timestamp>.<body>``, so a receiver can reject old
    deliveries replayed with their signature.
    """
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


class WebhookDispatcher:
    """Sends queued webhook deliveries, signed with each webhook's secret.

    A delivery is delivered when the receiver answers 2xx. Anything else is
    tried again after ``retry_delays``, then marked failed. Any number of
    dispatchers can share the queue: a claimed delivery is not due again
    for ``lease_seconds``.
    """

    def __init__(self, unit_of_work: Callable[[], AbstractAsyncContextManager[UnitOfWork]],
                 sender: WebhookSender, *, lease_seconds: int = 120, poll_seconds: float = 1.0,
                 retry_delays: Sequence[float] = RETRY_DELAYS,
                 clock: Callable[[], float] = time.time):
        self.unit_of_work = unit_of_work
        self.sender = sender
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.retry_delays = retry_delays
        self.clock = clock

    async def run(self) -> None:
        """Send deliveries as they come, until cancelled."""
        while True:
            try:
                sent = await self.deliver_next()
            except Exception:
                logger.exception("Could not take the next webhook delivery")
                sent = False
            if not sent:
                await asyncio.sleep(self.poll_seconds)

    async def deliver_next(self) -> bool:
        """Attempt the next due delivery, if any; returns whether there was one."""
        async with self.unit_of_work() as uow:
            claimed = await uow.webhooks.claim_delivery(self.lease_seconds)
            await uow.commit()
        if claimed is None:
            return False
        delivery, webhook = claimed
        with log_context(f"delivery:{delivery.id}"):
            await self._deliver(delivery, webhook)
        return True

    async def _deliver(self, delivery: WebhookDelivery, webhook: Webhook) -> None:
        body = json.dumps({"id": delivery.id, **delivery.payload},
                          separators=(",", ":"), ensure_ascii=False).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ragolex-webhooks",
            "X-Ragolex-Event": delivery.event,
            "X-Ragolex-Delivery": delivery.id,
            "X-Ragolex-Signature": signature(webhook.secret, int(self.clock()), body),
        }
        status, error = None, None
        try:
            status = await self.sender.send(webhook.url, body, headers)
            if not 200 <= status < 300:
                error = f"HTTP {status}"
        except WebhookFailed as exc:
            error = str(exc)

        retry_at = None
        if error and delivery.attempts <= len(self.retry_delays):
            retry_at = datetime.now(UTC) + timedelta(
                seconds=self.retry_delays[delivery.attempts - 1])
        async with self.unit_of_work() as uow:
            await uow.webhooks.record_attempt(delivery.id, delivered=error is None,
                                              response_status=status, error=error,
                                              retry_at=retry_at)
            await uow.commit()
        WEBHOOK_DELIVERIES.labels(
            outcome="delivered" if error is None else "retried" if retry_at else "failed").inc()
        if error:
            then = f"trying again at {retry_at.isoformat()}" if retry_at else "giving up"
            logger.warning("Webhook delivery %s (%s) to %s failed: %s; %s", delivery.id,
                           delivery.event, webhook.url, error, then)
