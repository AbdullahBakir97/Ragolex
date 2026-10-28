"""A project's assistants in Telegram, Slack and WhatsApp, and the webhook they receive on.

Admins add a bot with its chat app's credentials. The chat app then sends
every message to the bot's webhook, which checks the app's signature,
answers the app at once (apps wait only seconds), and has the answer sent
to the chat afterwards, from a background task with its own session.
"""

import logging
from collections.abc import Mapping

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from ragolex.api.dependencies import (
    ADMIN,
    BotServiceDep,
    SessionDep,
    background_answer_service,
)
from ragolex.api.schemas import (
    BotIdPath,
    BotListResponse,
    BotRequest,
    BotResponse,
    BotUpdateRequest,
    ProjectId,
    error_responses,
)
from ragolex.bots.inbound import read_delivery, whatsapp_challenge
from ragolex.core import log_context
from ragolex.core.config import get_settings
from ragolex.core.errors import (
    BotCredentialsInvalid,
    BotNotFound,
    BotPlatformFailed,
    BotSignatureInvalid,
    ProjectNotFound,
)
from ragolex.domain.models import Bot, IncomingMessage
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.bot_service import BotService
from ragolex.services.limit_service import LimitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["bots"], dependencies=[ADMIN])
public_router = APIRouter(prefix="/api/v1/bots", tags=["bot webhooks"])

# Chat apps' messages are small; anything larger is not one of theirs.
MAX_DELIVERY_BYTES = 1_000_000


async def _bot(bot: Bot, service: BotService) -> BotResponse:
    return BotResponse(id=bot.id, project=bot.project_name, kind=bot.kind,  # type: ignore[arg-type]
                       name=bot.name, account=bot.account, tags=list(bot.tags),
                       enabled=bot.enabled, webhook_url=await service.webhook_url(bot),
                       verify_token=bot.webhook_secret if bot.kind == "whatsapp" else None,
                       created_at=bot.created_at, last_message_at=bot.last_message_at,
                       last_error=bot.last_error, last_error_at=bot.last_error_at)


@router.post("/{project_id}/bots", status_code=status.HTTP_201_CREATED,
             summary="Add a bot that answers in Telegram, Slack or WhatsApp",
             description="The chat app is asked to accept the credentials first. Telegram is "
                         "told the webhook URL; for Slack and WhatsApp, paste `webhook_url` "
                         "(and WhatsApp's `verify_token`) into the app's settings.",
             responses=error_responses(ProjectNotFound, BotCredentialsInvalid,
                                       BotPlatformFailed))
async def create_bot(project_id: ProjectId, body: BotRequest,
                     service: BotServiceDep) -> BotResponse:
    bot = await service.create(project_id, body.kind, body.name, body.credentials, body.tags)
    return await _bot(bot, service)


@router.get("/{project_id}/bots", summary="The project's bots, oldest first",
            responses=error_responses(ProjectNotFound))
async def list_bots(project_id: ProjectId, service: BotServiceDep) -> BotListResponse:
    return BotListResponse(items=[await _bot(bot, service)
                                  for bot in await service.bots(project_id)])


@router.get("/{project_id}/bots/{bot_id}", summary="A bot",
            responses=error_responses(ProjectNotFound, BotNotFound))
async def get_bot(project_id: ProjectId, bot_id: BotIdPath,
                  service: BotServiceDep) -> BotResponse:
    return await _bot(await service.get(project_id, bot_id), service)


@router.patch("/{project_id}/bots/{bot_id}", summary="Change a bot",
              description="Its name, tags, whether it answers, or its credentials (checked "
                          "with the chat app first).",
              responses=error_responses(ProjectNotFound, BotNotFound, BotCredentialsInvalid,
                                        BotPlatformFailed))
async def update_bot(project_id: ProjectId, bot_id: BotIdPath, body: BotUpdateRequest,
                     service: BotServiceDep) -> BotResponse:
    changes = body.model_dump(exclude_unset=True)
    return await _bot(await service.update(project_id, bot_id, changes), service)


@router.delete("/{project_id}/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a bot",
               description="Telegram stops sending it messages; its conversations stay with "
                           "the project.",
               responses=error_responses(ProjectNotFound, BotNotFound))
async def delete_bot(project_id: ProjectId, bot_id: BotIdPath,
                     service: BotServiceDep) -> Response:
    await service.delete(project_id, bot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _find(session: SessionDep, bot_id: str) -> Bot:
    bot = await SqlUnitOfWork(session).bots.get(bot_id)
    if bot is None:
        raise BotNotFound()
    log_context.tenant.set(bot.tenant_name)
    return bot


@public_router.post(
    "/{bot_id}/webhook", summary="Where a chat app delivers a bot's messages",
    description="Checked with the app's signature (Telegram's secret token, Slack's signing "
                "secret, WhatsApp's app secret). Answers at once; the reply is sent to the "
                "chat when it is written. A delivery sent again is answered once.",
    responses=error_responses(BotNotFound, BotSignatureInvalid))
async def bot_webhook(bot_id: BotIdPath, request: Request, session: SessionDep,
                      background: BackgroundTasks) -> Response:
    bot = await _find(session, bot_id)
    body = await request.body()
    if len(body) > MAX_DELIVERY_BYTES:
        return Response(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    delivery = read_delivery(bot, request.headers, body)
    if delivery.challenge is not None:  # Slack checking the Request URL.
        return JSONResponse({"challenge": delivery.challenge})
    if bot.enabled:
        for message in delivery.messages:
            background.add_task(answer_message, request.app, bot.id, message)
    return Response(status_code=status.HTTP_200_OK)


@public_router.get(
    "/{bot_id}/webhook", summary="WhatsApp checking the callback URL",
    description="Echoes `hub.challenge` when `hub.verify_token` is the bot's verify token.",
    response_class=PlainTextResponse, responses=error_responses(BotNotFound, BotSignatureInvalid))
async def bot_webhook_check(bot_id: BotIdPath, request: Request,
                            session: SessionDep) -> PlainTextResponse:
    bot = await _find(session, bot_id)
    if bot.kind != "whatsapp":
        raise BotSignatureInvalid()
    params: Mapping[str, str] = request.query_params
    return PlainTextResponse(whatsapp_challenge(bot, params))


async def answer_message(app: FastAPI, bot_id: str, message: IncomingMessage) -> None:
    """Answer one message in its chat, after the webhook answered the app."""
    settings = get_settings()
    try:
        async with app.state.session_factory() as session:
            bot = await SqlUnitOfWork(session).bots.get(bot_id)
            if bot is None or not bot.enabled:
                return
            log_context.tenant.set(bot.tenant_name)
            uow = SqlUnitOfWork(session, bot.tenant_id)
            limits = LimitService(SqlUnitOfWork(session), settings.default_limits)
            service = BotService(uow, app.state.chat_platforms, app_url=settings.APP_URL)
            await service.respond(
                bot, message, lambda: background_answer_service(app, uow, settings, limits),
                limits)
    except Exception:
        # Nobody waits for this; the log is where it shows.
        logger.exception("Bot %s: a message could not be answered", bot_id)
