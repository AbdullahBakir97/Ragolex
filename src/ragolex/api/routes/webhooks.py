from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ragolex.api.dependencies import ADMIN, WebhookServiceDep
from ragolex.api.schemas import (
    DeliveryListResponse,
    DeliveryResponse,
    Pagination,
    ProjectId,
    WebhookCreatedResponse,
    WebhookIdPath,
    WebhookListResponse,
    WebhookRequest,
    WebhookResponse,
    error_responses,
)
from ragolex.core.errors import ProjectNotFound, WebhookNotFound, WebhookUrlNotAllowed
from ragolex.domain.models import Webhook, WebhookDelivery

router = APIRouter(prefix="/api/v1/projects", tags=["webhooks"], dependencies=[ADMIN])

PaginationDep = Annotated[Pagination, Depends()]


def _webhook(webhook: Webhook) -> dict:
    return {"id": webhook.id, "url": webhook.url, "events": list(webhook.events),
            "description": webhook.description, "created_at": webhook.created_at}


def _delivery(delivery: WebhookDelivery) -> DeliveryResponse:
    return DeliveryResponse(
        id=delivery.id, event=delivery.event, status=delivery.status,
        attempts=delivery.attempts, response_status=delivery.response_status,
        error=delivery.error, created_at=delivery.created_at,
        next_attempt_at=delivery.next_attempt_at if delivery.status == "pending" else None,
        delivered_at=delivery.delivered_at, payload=delivery.payload)


@router.post("/{project_id}/webhooks", status_code=status.HTTP_201_CREATED,
             summary="Send a project's events to a URL",
             description="Each event is POSTed as JSON, signed with the returned `secret` "
                         "(see X-Ragolex-Signature), and retried for about 20 hours until "
                         "the URL answers 2xx. The project is created if it has no files yet.",
             responses=error_responses(WebhookUrlNotAllowed))
async def create_webhook(project_id: ProjectId, request: WebhookRequest,
                         service: WebhookServiceDep) -> WebhookCreatedResponse:
    webhook = await service.create(project_id, str(request.url), request.events,
                                   request.description)
    return WebhookCreatedResponse(**_webhook(webhook), secret=webhook.secret)


@router.get("/{project_id}/webhooks", summary="List a project's webhooks",
            responses=error_responses(ProjectNotFound))
async def list_webhooks(project_id: ProjectId, page: PaginationDep,
                        service: WebhookServiceDep) -> WebhookListResponse:
    result = await service.list(project_id, offset=page.offset, limit=page.limit)
    return WebhookListResponse(total=result.total, offset=page.offset, limit=page.limit,
                               items=[WebhookResponse(**_webhook(w)) for w in result.items])


@router.get("/{project_id}/webhooks/{webhook_id}", summary="A webhook",
            responses=error_responses(ProjectNotFound, WebhookNotFound))
async def get_webhook(project_id: ProjectId, webhook_id: WebhookIdPath,
                      service: WebhookServiceDep) -> WebhookResponse:
    return WebhookResponse(**_webhook(await service.get(project_id, str(webhook_id))))


@router.delete("/{project_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Stop sending events to a webhook, and forget its deliveries",
               responses=error_responses(ProjectNotFound, WebhookNotFound))
async def delete_webhook(project_id: ProjectId, webhook_id: WebhookIdPath,
                         service: WebhookServiceDep) -> Response:
    await service.delete(project_id, str(webhook_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/webhooks/{webhook_id}/ping", status_code=status.HTTP_202_ACCEPTED,
             summary="Send a ping event, to check the webhook is reached",
             responses=error_responses(ProjectNotFound, WebhookNotFound))
async def ping_webhook(project_id: ProjectId, webhook_id: WebhookIdPath,
                       service: WebhookServiceDep) -> DeliveryResponse:
    return _delivery(await service.ping(project_id, str(webhook_id)))


@router.get("/{project_id}/webhooks/{webhook_id}/deliveries",
            summary="What was sent to a webhook, most recent first",
            responses=error_responses(ProjectNotFound, WebhookNotFound))
async def list_deliveries(project_id: ProjectId, webhook_id: WebhookIdPath, page: PaginationDep,
                          service: WebhookServiceDep) -> DeliveryListResponse:
    result = await service.deliveries(project_id, str(webhook_id), offset=page.offset,
                                      limit=page.limit)
    return DeliveryListResponse(total=result.total, offset=page.offset, limit=page.limit,
                                items=[_delivery(d) for d in result.items])
