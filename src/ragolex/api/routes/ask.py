import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ragolex.api.dependencies import ANSWER_QUOTA, ASK, AnswerServiceDep
from ragolex.api.schemas import (
    AskRequest,
    AskResponse,
    CitationResponse,
    ProjectId,
    SearchStepResponse,
    UsageResponse,
    error_responses,
)
from ragolex.core.errors import (
    AppError,
    ConversationNotFound,
    EmbeddingFailed,
    EmbeddingNotConfigured,
    FileNotFound,
    LLMFailed,
    LLMNotConfigured,
    ProjectNotFound,
)
from ragolex.domain.models import SearchFilters
from ragolex.domain.signals import ResponseSignal
from ragolex.services.answer_service import Answer, AnswerDelta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ask", tags=["ask"], dependencies=[ASK, ANSWER_QUOTA])

ASK_ERRORS = error_responses(ProjectNotFound, ConversationNotFound, FileNotFound, EmbeddingFailed,
                             LLMFailed, EmbeddingNotConfigured, LLMNotConfigured)


def ask_response(answer: Answer) -> AskResponse:
    return AskResponse(
        signal=ResponseSignal.ANSWER_SUCCESS if answer.text is not None else ResponseSignal.NO_ANSWER,
        answer=answer.text,
        citations=[CitationResponse(number=citation.number, file_id=citation.source.file_key,
                                    chunk_index=citation.source.chunk.index,
                                    page=citation.source.chunk.metadata.get("page"),
                                    section=citation.source.chunk.metadata.get("section"),
                                    score=citation.source.score, text=citation.source.chunk.text)
                   for citation in answer.citations],
        prompt_version=answer.prompt_version,
        usage=UsageResponse(
            input_tokens=answer.usage.input_tokens if answer.usage else None,
            output_tokens=answer.usage.output_tokens if answer.usage else None,
            cost_usd=answer.cost_usd),
        conversation_id=answer.conversation_id,
        search_question=answer.search_question,
        message_id=answer.message_id,
        research=None if answer.research is None else [
            SearchStepResponse(query=step.query, results=step.results) for step in answer.research])


@router.post(
    "/{project_id}",
    summary="Answer a question from the project's documents",
    description="Finds the indexed chunks that best match the question and has a language model "
                "answer from them, citing each source as [n]. Signal `no_answer`, with `answer` "
                "null, means the documents do not answer the question. With `conversation_id`, "
                "the question is a follow-up: it is first rewritten into a standalone question "
                "from the conversation so far, and the question and the answer are added to the "
                "conversation.",
    responses=ASK_ERRORS,
)
async def ask_project(project_id: ProjectId, request: AskRequest,
                      service: AnswerServiceDep) -> AskResponse:
    answer = await service.ask(project_id, request.question, top_k=request.top_k,
                               min_score=request.min_score,
                               conversation_id=_conversation_id(request),
                               filters=_filters(request), research_steps=request.research_steps)
    return ask_response(answer)


def _conversation_id(request: AskRequest) -> str | None:
    return str(request.conversation_id) if request.conversation_id else None


def _filters(request: AskRequest) -> SearchFilters | None:
    return request.filters.to_filters() if request.filters else None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/{project_id}/stream",
    summary="Answer a question, streaming the answer as it is written",
    description="The same answer as POST /api/v1/ask/{project_id}, as Server-Sent Events: "
                "`delta` events carry the next piece of text (`{\"text\": ...}`), then one "
                "`answer` event carries the full response, with its citations. A `no_answer` "
                "reply sends no `delta` events. If the model fails mid-answer, an `error` event "
                "(`{\"signal\": \"llm_failed\"}`) ends the stream. Errors before the stream "
                "starts are returned as usual.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Events: `delta`, then `answer` or `error`."},
               **ASK_ERRORS},
)
async def ask_project_stream(project_id: ProjectId, request: AskRequest,
                             service: AnswerServiceDep) -> StreamingResponse:
    # Prepare first, so a missing project or conversation, or a failing
    # embedder, is still an ordinary error response rather than an event.
    prepared = await service.prepare(project_id, request.question, top_k=request.top_k,
                                     min_score=request.min_score,
                                     conversation_id=_conversation_id(request),
                                     filters=_filters(request),
                                     research_steps=request.research_steps)

    async def events() -> AsyncIterator[str]:
        try:
            async for event in service.stream(prepared):
                if isinstance(event, AnswerDelta):
                    yield sse("delta", {"text": event.text})
                else:
                    yield sse("answer", ask_response(event).model_dump(mode="json"))
        except AppError as exc:
            logger.error("POST /api/v1/ask/%s/stream failed: %s", project_id, exc,
                         exc_info=exc.__cause__ or exc)
            yield sse("error", {"signal": exc.signal.value})

    # No caching or proxy buffering, so each event reaches the client at once.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
