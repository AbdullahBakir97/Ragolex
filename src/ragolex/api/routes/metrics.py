import hmac

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Gauge, generate_latest

from ragolex.api.dependencies import SessionDep, SettingsDep
from ragolex.core.errors import ApiKeyInvalid, ApiKeyRequired
from ragolex.persistence.metrics import queue_depths

router = APIRouter(include_in_schema=False)

JOBS = Gauge("ragolex_jobs_in_state", "Background jobs, by status.", ["status"])
WEBHOOK_DELIVERIES = Gauge("ragolex_webhook_deliveries_in_state",
                           "Webhook deliveries, by status.", ["status"])


@router.get("/metrics")
async def metrics(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    """Prometheus metrics; with METRICS_TOKEN set, only for `Authorization: Bearer <token>`."""
    if settings.METRICS_TOKEN:
        sent = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not sent:
            raise ApiKeyRequired()
        if not hmac.compare_digest(sent.encode(), settings.METRICS_TOKEN.encode()):
            raise ApiKeyInvalid()
    depths = await queue_depths(session)
    for status in ("queued", "running", "succeeded", "failed"):
        JOBS.labels(status).set(depths["jobs"].get(status, 0))
    for status in ("pending", "delivered", "failed"):
        WEBHOOK_DELIVERIES.labels(status).set(depths["webhook_deliveries"].get(status, 0))
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
