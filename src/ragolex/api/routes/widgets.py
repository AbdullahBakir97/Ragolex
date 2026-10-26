"""Chat widgets: managed by the tenant, used by the visitors of the websites that embed them.

The public routes take no API key. A widget acts for its tenant on its one
project, can only ask it, and counts against the tenant's rate limit and
answer quota; the widget id in a page's script tag is all a visitor has.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from ragolex.api.dependencies import (
    ADMIN,
    EmbedderDep,
    LimitServiceDep,
    LLMDep,
    SessionDep,
    SettingsDep,
    WidgetServiceDep,
    get_answer_service,
    get_search_service,
)
from ragolex.api.routes.ask import sse
from ragolex.api.schemas import (
    ConversationIdPath,
    FeedbackRequest,
    MessageIdPath,
    ProjectId,
    WidgetAnswer,
    WidgetAskRequest,
    WidgetCitation,
    WidgetConfigResponse,
    WidgetIdPath,
    WidgetListResponse,
    WidgetRequest,
    WidgetResponse,
    WidgetUpdateRequest,
    error_responses,
)
from ragolex.core import log_context
from ragolex.core.errors import (
    AnswerQuotaExceeded,
    AppError,
    ConversationNotFound,
    EmbeddingFailed,
    EmbeddingNotConfigured,
    LLMFailed,
    LLMNotConfigured,
    MessageNotFound,
    OriginNotAllowed,
    ProjectNotFound,
    RateLimited,
    WidgetNotFound,
    WidgetOriginInvalid,
)
from ragolex.domain.models import SearchFilters, Widget
from ragolex.domain.repositories import UnitOfWork
from ragolex.domain.signals import ResponseSignal
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.answer_service import Answer, AnswerDelta, AnswerService
from ragolex.services.conversation_service import ConversationService
from ragolex.services.limit_service import rate_headers
from ragolex.services.widget_service import WidgetService

logger = logging.getLogger(__name__)

# Every widget question uses the same number of sources.
WIDGET_TOP_K = 5

router = APIRouter(prefix="/api/v1/projects", tags=["widgets"], dependencies=[ADMIN])
public_router = APIRouter(prefix="/api/v1/widgets", tags=["widget visitors"])


def _widget(widget: Widget) -> WidgetResponse:
    return WidgetResponse(id=widget.id, project=widget.project_name, name=widget.name,
                          welcome=widget.welcome, accent=widget.accent,
                          allowed_origins=list(widget.allowed_origins),
                          tags=list(widget.tags), logo_url=widget.logo_url,
                          created_at=widget.created_at)


@router.post("/{project_id}/widgets", status_code=status.HTTP_201_CREATED,
             summary="Add a chat widget for a project's documents",
             description="Embed it with `<script src=\"https://<web app>/widget.js\" "
                         "data-widget=\"<id>\" async></script>`. Visitors of the allowed "
                         "websites can then ask the project, without an API key.",
             responses=error_responses(ProjectNotFound, WidgetOriginInvalid))
async def create_widget(project_id: ProjectId, request: WidgetRequest,
                        service: WidgetServiceDep) -> WidgetResponse:
    return _widget(await service.create(project_id, request.name, request.welcome,
                                        request.accent, request.allowed_origins, request.tags,
                                        request.logo_url))


@router.get("/{project_id}/widgets", summary="List a project's chat widgets",
            responses=error_responses(ProjectNotFound))
async def list_widgets(project_id: ProjectId, service: WidgetServiceDep) -> WidgetListResponse:
    return WidgetListResponse(items=[_widget(w) for w in await service.list(project_id)])


@router.get("/{project_id}/widgets/{widget_id}", summary="A chat widget",
            responses=error_responses(ProjectNotFound, WidgetNotFound))
async def get_widget(project_id: ProjectId, widget_id: WidgetIdPath,
                     service: WidgetServiceDep) -> WidgetResponse:
    return _widget(await service.get(project_id, widget_id))


@router.patch("/{project_id}/widgets/{widget_id}", summary="Change a chat widget",
              description="Only the fields sent change. Pages already open pick the changes "
                          "up when they are loaded again.",
              responses=error_responses(ProjectNotFound, WidgetNotFound, WidgetOriginInvalid))
async def update_widget(project_id: ProjectId, widget_id: WidgetIdPath,
                        request: WidgetUpdateRequest, service: WidgetServiceDep) -> WidgetResponse:
    return _widget(await service.update(project_id, widget_id,
                                        request.model_dump(exclude_unset=True)))


@router.delete("/{project_id}/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a chat widget",
               description="Pages that embed it stop showing it. The conversations visitors "
                           "had in it stay with the project.",
               responses=error_responses(ProjectNotFound, WidgetNotFound))
async def delete_widget(project_id: ProjectId, widget_id: WidgetIdPath,
                        service: WidgetServiceDep) -> Response:
    await service.delete(project_id, widget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Visitors' routes.

async def open_widget(widget_id: WidgetIdPath, request: Request, session: SessionDep,
                      limits: LimitServiceDep, response: Response) -> Widget:
    """The widget, if the page asking may use it; counted against its tenant's rate limit."""
    widget = await WidgetService(SqlUnitOfWork(session)).open(
        widget_id, request.headers.get("origin"), request.headers.get("host"))
    log_context.tenant.set(widget.tenant_name)
    response.headers.update(rate_headers(await limits.count_request(widget.tenant_id)))
    return widget


WidgetDep = Annotated[Widget, Depends(open_widget)]


def get_widget_unit_of_work(session: SessionDep, widget: WidgetDep) -> UnitOfWork:
    return SqlUnitOfWork(session, widget.tenant_id)


WidgetUnitOfWorkDep = Annotated[UnitOfWork, Depends(get_widget_unit_of_work)]


def get_widget_answers(request: Request, uow: WidgetUnitOfWorkDep, settings: SettingsDep,
                       embedder: EmbedderDep, llm: LLMDep) -> AnswerService:
    search = get_search_service(request, uow, embedder, settings)
    return get_answer_service(search, llm, uow, settings)


VISITOR_ERRORS = (WidgetNotFound, OriginNotAllowed, RateLimited)


@public_router.get("/{widget_id}", summary="What a widget shows",
                   responses=error_responses(*VISITOR_ERRORS))
async def widget_config(widget: WidgetDep) -> WidgetConfigResponse:
    return WidgetConfigResponse(id=widget.id, name=widget.name, welcome=widget.welcome,
                                accent=widget.accent, logo_url=widget.logo_url)


@public_router.post(
    "/{widget_id}/ask",
    summary="Answer a visitor's question, streaming the answer as it is written",
    description="Server-Sent Events, as POST /api/v1/ask/{project_id}/stream: `delta` events "
                "with the next piece of text, then one `answer` event (a `WidgetAnswer`), or an "
                "`error` event. Without `conversation_id`, a conversation is started; send the "
                "answer's `conversation_id` with the next question to follow on from it.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Events: `delta`, then `answer` or `error`."},
               **error_responses(*VISITOR_ERRORS, AnswerQuotaExceeded, ConversationNotFound,
                                 EmbeddingFailed, EmbeddingNotConfigured, LLMNotConfigured,
                                 LLMFailed)},
)
async def widget_ask(widget: WidgetDep, body: WidgetAskRequest, uow: WidgetUnitOfWorkDep,
                     limits: LimitServiceDep,
                     answers: Annotated[AnswerService, Depends(get_widget_answers)],
                     ) -> StreamingResponse:
    await limits.check_answers(widget.tenant_id)
    conversation = await WidgetService(uow).conversation(
        widget, str(body.conversation_id) if body.conversation_id else None)
    # A widget with tags answers only from the files that have them.
    filters = SearchFilters(tags=widget.tags) if widget.tags else None
    prepared = await answers.prepare(widget.project_name, body.question, top_k=WIDGET_TOP_K,
                                     conversation_id=conversation.id, filters=filters)
    # Visitors see documents' names, not their ids.
    names = {}
    for source in prepared.sources:
        if source.file_key not in names:
            record = await uow.files.get_by_key(widget.project_id, source.file_key)
            names[source.file_key] = record.original_name if record else None

    def answer_event(answer: Answer) -> WidgetAnswer:
        return WidgetAnswer(
            signal=ResponseSignal.ANSWER_SUCCESS if answer.text is not None
            else ResponseSignal.NO_ANSWER,
            answer=answer.text,
            citations=[WidgetCitation(number=c.number, file_name=names.get(c.source.file_key),
                                      page=c.source.chunk.metadata.get("page"),
                                      section=c.source.chunk.metadata.get("section"),
                                      text=c.source.chunk.text)
                       for c in answer.citations],
            conversation_id=conversation.id, message_id=answer.message_id)

    async def events() -> AsyncIterator[str]:
        try:
            async for event in answers.stream(prepared):
                if isinstance(event, AnswerDelta):
                    yield sse("delta", {"text": event.text})
                else:
                    yield sse("answer", answer_event(event).model_dump(mode="json"))
        except AppError as exc:
            logger.error("Widget %s: answering failed: %s", widget.id, exc,
                         exc_info=exc.__cause__ or exc)
            yield sse("error", {"signal": exc.signal.value})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@public_router.put(
    "/{widget_id}/conversations/{conversation_id}/messages/{message_id}/feedback",
    summary="Rate an answer thumbs up or down",
    description="Only in a conversation started in this widget. The rating shows with the "
                "project's other feedback.",
    responses=error_responses(*VISITOR_ERRORS, ConversationNotFound, MessageNotFound))
async def widget_feedback(widget: WidgetDep, conversation_id: ConversationIdPath,
                          message_id: MessageIdPath, body: FeedbackRequest,
                          uow: WidgetUnitOfWorkDep) -> Response:
    conversation = await WidgetService(uow).conversation(widget, str(conversation_id))
    await ConversationService(uow).rate(widget.project_name, conversation.id, message_id,
                                        body.rating, body.comment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
