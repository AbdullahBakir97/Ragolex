from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from ragolex.api.dependencies import ASK, READ, ConversationServiceDep
from ragolex.api.schemas import (
    CitationResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationIdPath,
    ConversationListResponse,
    ConversationResponse,
    FeedbackListResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageIdPath,
    MessageResponse,
    Pagination,
    ProjectId,
    RatedAnswerResponse,
    error_responses,
)
from ragolex.core.errors import ConversationNotFound, MessageNotFound, ProjectNotFound
from ragolex.domain.models import (
    Conversation,
    ConversationMessage,
    Feedback,
    StoredCitation,
)

router = APIRouter(prefix="/api/v1/projects", tags=["conversations"])

PaginationDep = Annotated[Pagination, Depends()]


def _conversation(conversation: Conversation) -> dict:
    return {"id": conversation.id, "title": conversation.title,
            "created_at": conversation.created_at, "updated_at": conversation.updated_at,
            "widget_id": conversation.widget_id}


def _citations(citations: list[StoredCitation]) -> list[CitationResponse]:
    return [CitationResponse(number=c.number, file_id=c.file_key, chunk_index=c.chunk_index,
                             page=c.page, section=c.section, score=c.score, text=c.text)
            for c in citations]


def _feedback(feedback: Feedback | None) -> FeedbackResponse | None:
    return None if feedback is None else _given_feedback(feedback)


def _given_feedback(feedback: Feedback) -> FeedbackResponse:
    assert feedback.created_at is not None  # Feedback read back is stored.
    return FeedbackResponse(rating=feedback.rating, comment=feedback.comment,
                            created_at=feedback.created_at)


def _message(message: ConversationMessage) -> MessageResponse:
    assert message.id is not None and message.created_at is not None  # Read back, so stored.
    return MessageResponse(
        id=message.id, role=message.role, content=message.content,
        citations=_citations(message.citations),
        prompt_version=message.prompt_version, search_question=message.search_question,
        created_at=message.created_at, feedback=_feedback(message.feedback))


@router.post("/{project_id}/conversations", dependencies=[ASK], status_code=status.HTTP_201_CREATED,
             summary="Start a conversation",
             description="Ask in it with POST /api/v1/ask/{project_id} and its `conversation_id`.",
             responses=error_responses(ProjectNotFound))
async def create_conversation(project_id: ProjectId, service: ConversationServiceDep,
                              request: ConversationCreateRequest | None = None,
                              ) -> ConversationResponse:
    conversation = await service.create(project_id, request.title if request else None)
    return ConversationResponse(**_conversation(conversation))


@router.get("/{project_id}/conversations", dependencies=[READ],
            summary="List conversations, most recent first",
            responses=error_responses(ProjectNotFound))
async def list_conversations(project_id: ProjectId, page: PaginationDep,
                             service: ConversationServiceDep) -> ConversationListResponse:
    result = await service.list(project_id, offset=page.offset, limit=page.limit)
    return ConversationListResponse(
        total=result.total, offset=result.offset, limit=result.limit,
        items=[ConversationResponse(**_conversation(c)) for c in result.items])


@router.get("/{project_id}/conversations/{conversation_id}", dependencies=[READ],
            summary="A conversation with its questions and answers",
            responses=error_responses(ProjectNotFound, ConversationNotFound))
async def get_conversation(project_id: ProjectId, conversation_id: ConversationIdPath,
                           service: ConversationServiceDep) -> ConversationDetailResponse:
    found = await service.get(project_id, str(conversation_id))
    return ConversationDetailResponse(**_conversation(found.conversation),
                                      messages=[_message(m) for m in found.messages])


@router.delete("/{project_id}/conversations/{conversation_id}", dependencies=[ASK],
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a conversation and its messages",
               responses=error_responses(ProjectNotFound, ConversationNotFound))
async def delete_conversation(project_id: ProjectId, conversation_id: ConversationIdPath,
                              service: ConversationServiceDep) -> Response:
    await service.delete(project_id, str(conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


FEEDBACK_ERRORS = error_responses(ProjectNotFound, ConversationNotFound, MessageNotFound)
FEEDBACK_PATH = "/{project_id}/conversations/{conversation_id}/messages/{message_id}/feedback"


@router.put(FEEDBACK_PATH, dependencies=[ASK], summary="Rate an answer thumbs up or down",
            description="Replaces any rating the answer had. Rated answers can be reviewed with "
                        "GET /api/v1/projects/{project_id}/feedback and exported as evaluation "
                        "cases with `ragolex feedback-export`.",
            responses=FEEDBACK_ERRORS)
async def rate_answer(project_id: ProjectId, conversation_id: ConversationIdPath,
                      message_id: MessageIdPath, request: FeedbackRequest,
                      service: ConversationServiceDep) -> MessageResponse:
    message = await service.rate(project_id, str(conversation_id), message_id,
                                 request.rating, request.comment)
    return _message(message)


@router.delete(FEEDBACK_PATH, dependencies=[ASK], status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove an answer's rating", responses=FEEDBACK_ERRORS)
async def unrate_answer(project_id: ProjectId, conversation_id: ConversationIdPath,
                        message_id: MessageIdPath, service: ConversationServiceDep) -> Response:
    await service.unrate(project_id, str(conversation_id), message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/feedback", dependencies=[READ],
            summary="Rated answers, most recently rated first",
            responses=error_responses(ProjectNotFound))
async def list_feedback(project_id: ProjectId, page: PaginationDep, service: ConversationServiceDep,
                        rating: Annotated[Literal["up", "down"] | None,
                                          Query(description="Only this rating.")] = None,
                        ) -> FeedbackListResponse:
    result = await service.feedback(project_id, rating, page.offset, page.limit)
    return FeedbackListResponse(
        up=result.counts.up, down=result.counts.down, total=result.page.total,
        offset=result.page.offset, limit=result.page.limit,
        items=[RatedAnswerResponse(conversation_id=item.conversation_id,
                                   message_id=item.message_id, question=item.question,
                                   answer=item.answer, citations=_citations(item.citations),
                                   feedback=_given_feedback(item.feedback))
               for item in result.page.items])
