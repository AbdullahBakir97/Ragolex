from typing import Annotated

from fastapi import APIRouter, Depends

from ragolex.api.dependencies import (
    ANSWER_QUOTA,
    ASK,
    LLMDep,
    SettingsDep,
    UnitOfWorkDep,
)
from ragolex.api.schemas import (
    FlashcardResponse,
    KeyPointResponse,
    ProjectId,
    QuizQuestionResponse,
    StudyRequest,
    StudyResponse,
    StudySourceResponse,
    UsageResponse,
    error_responses,
)
from ragolex.core.errors import (
    FileNotFound,
    FileNotProcessed,
    LLMFailed,
    LLMNotConfigured,
    ProjectNotFound,
)
from ragolex.domain.models import Flashcard, KeyPoint, QuizQuestion, StudyItem
from ragolex.services.study_service import StudyService

router = APIRouter(prefix="/api/v1/study", tags=["study"], dependencies=[ASK, ANSWER_QUOTA])


def get_study_service(uow: UnitOfWorkDep, llm: LLMDep, settings: SettingsDep) -> StudyService:
    return StudyService(uow=uow, llm=llm, prices=settings.llm_prices,
                        max_characters=settings.STUDY_MAX_CHARACTERS)


@router.post(
    "/{project_id}",
    summary="Write a summary, flashcards or a quiz from a document",
    description="Gives the document's chunks to the language model (spread evenly over a long "
                "document) and returns study material of the requested kind. Each item cites "
                "the passages it comes from, with their page or section. Costs a model call, "
                "counted like an answer in usage and the answer quota.",
    responses=error_responses(ProjectNotFound, FileNotFound, FileNotProcessed, LLMFailed,
                              LLMNotConfigured),
)
async def study(project_id: ProjectId, request: StudyRequest,
                service: Annotated[StudyService, Depends(get_study_service)]) -> StudyResponse:
    material = await service.generate(project_id, request.file_id, request.kind, request.count)
    return StudyResponse(
        kind=material.kind, file_id=material.file_key, original_name=material.original_name,
        items=_items(material.items),
        sources=[StudySourceResponse(number=source.number, chunk_index=source.chunk_index,
                                     page=source.page, section=source.section, text=source.text)
                 for source in material.sources],
        prompt_version=material.prompt_version,
        usage=UsageResponse(
            input_tokens=material.usage.input_tokens if material.usage else None,
            output_tokens=material.usage.output_tokens if material.usage else None,
            cost_usd=material.cost_usd),
        passages=material.passages, chunks=material.chunks)


def _items(items: list[StudyItem]) -> (list[KeyPointResponse] | list[FlashcardResponse]
                                       | list[QuizQuestionResponse]):
    """The items, all of one kind."""
    if all(isinstance(item, KeyPoint) for item in items):
        return [KeyPointResponse(text=item.text, sources=list(item.sources))
                for item in items if isinstance(item, KeyPoint)]
    if all(isinstance(item, Flashcard) for item in items):
        return [FlashcardResponse(front=item.front, back=item.back, sources=list(item.sources))
                for item in items if isinstance(item, Flashcard)]
    return [QuizQuestionResponse(question=item.question, choices=list(item.choices),
                                 answer=item.answer, explanation=item.explanation,
                                 sources=list(item.sources))
            for item in items if isinstance(item, QuizQuestion)]
