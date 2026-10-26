from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse

from ragolex.api.dependencies import READ, WRITE, UnitOfWorkDep
from ragolex.api.schemas import (
    CardIdPath,
    CardListResponse,
    CardRequest,
    CardResponse,
    CardSourceResponse,
    CardsRequest,
    DeckIdPath,
    DeckRequest,
    DeckResponse,
    Pagination,
    ProjectId,
    ReviewCardResponse,
    ReviewQueueResponse,
    ReviewRequest,
    error_responses,
)
from ragolex.core.errors import CardNotFound, DeckFull, DeckNotFound, ProjectNotFound
from ragolex.core.spaced_repetition import previews
from ragolex.domain.models import Card, CardSource, Deck
from ragolex.services.deck_service import DeckService, NewCard

router = APIRouter(prefix="/api/v1/projects/{project_id}/decks", tags=["decks"])

PaginationDep = Annotated[Pagination, Depends()]


def get_deck_service(uow: UnitOfWorkDep) -> DeckService:
    return DeckService(uow)


DeckServiceDep = Annotated[DeckService, Depends(get_deck_service)]
NOT_FOUND = (ProjectNotFound, DeckNotFound)


def _deck(deck: Deck) -> DeckResponse:
    return DeckResponse(id=deck.id, name=deck.name, cards=deck.cards, due=deck.due,
                        created_at=deck.created_at)


def _card_fields(card: Card) -> dict:
    source = card.source
    return {"id": card.id, "front": card.front, "back": card.back,
            "source": CardSourceResponse(file_id=source.file_key, chunk_index=source.chunk_index,
                                         page=source.page, section=source.section),
            "due_at": card.due_at, "interval_days": card.schedule.interval_days,
            "ease": card.schedule.ease, "repetitions": card.schedule.repetitions,
            "lapses": card.schedule.lapses, "last_reviewed_at": card.last_reviewed_at,
            "created_at": card.created_at}


def _new(cards: list[CardRequest]) -> list[NewCard]:
    return [NewCard(front=card.front, back=card.back,
                    source=CardSource(file_key=card.file_id, chunk_index=card.chunk_index,
                                      page=card.page, section=card.section))
            for card in cards]


@router.get("", dependencies=[READ], summary="List the project's decks, newest first",
            responses=error_responses(ProjectNotFound))
async def list_decks(project_id: ProjectId, service: DeckServiceDep) -> list[DeckResponse]:
    return [_deck(deck) for deck in await service.list(project_id)]


@router.post("", dependencies=[WRITE], status_code=status.HTTP_201_CREATED,
             summary="Create a deck of flashcards",
             description="Usually with the flashcards of `POST /study`; every card is new and "
                         "due at once.",
             responses=error_responses(ProjectNotFound))
async def create_deck(project_id: ProjectId, request: DeckRequest,
                      service: DeckServiceDep) -> DeckResponse:
    return _deck(await service.create(project_id, request.name, _new(request.cards)))


@router.get("/{deck_id}", dependencies=[READ], summary="A deck, with how many cards are due",
            responses=error_responses(*NOT_FOUND))
async def get_deck(project_id: ProjectId, deck_id: DeckIdPath,
                   service: DeckServiceDep) -> DeckResponse:
    return _deck(await service.get(project_id, str(deck_id)))


@router.delete("/{deck_id}", dependencies=[WRITE], status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a deck and its cards", responses=error_responses(*NOT_FOUND))
async def delete_deck(project_id: ProjectId, deck_id: DeckIdPath,
                      service: DeckServiceDep) -> Response:
    await service.delete(project_id, str(deck_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{deck_id}/cards", dependencies=[READ], summary="A deck's cards, in order",
            responses=error_responses(*NOT_FOUND))
async def list_cards(project_id: ProjectId, deck_id: DeckIdPath, page: PaginationDep,
                     service: DeckServiceDep) -> CardListResponse:
    result = await service.cards(project_id, str(deck_id), offset=page.offset, limit=page.limit)
    return CardListResponse(total=result.total, offset=result.offset, limit=result.limit,
                            items=[CardResponse(**_card_fields(card)) for card in result.items])


@router.post("/{deck_id}/cards", dependencies=[WRITE], summary="Add cards to a deck",
             description="After its other cards, new and due at once. A deck holds up to "
                         "2,000 cards.",
             responses=error_responses(*NOT_FOUND, DeckFull))
async def add_cards(project_id: ProjectId, deck_id: DeckIdPath, request: CardsRequest,
                    service: DeckServiceDep) -> DeckResponse:
    return _deck(await service.add_cards(project_id, str(deck_id), _new(request.cards)))


@router.get("/{deck_id}/review", dependencies=[READ], summary="The cards due for review now",
            description="The longest due first, each with the interval every grade would "
                        "give it. Review them one at a time with `POST .../review`.",
            responses=error_responses(*NOT_FOUND))
async def review_queue(project_id: ProjectId, deck_id: DeckIdPath, service: DeckServiceDep,
                       limit: Annotated[int, Query(ge=1, le=100)] = 20) -> ReviewQueueResponse:
    queue = await service.due(project_id, str(deck_id), limit)
    return ReviewQueueResponse(
        deck=_deck(queue.deck),
        cards=[ReviewCardResponse(**_card_fields(card), intervals=previews(card.schedule))
               for card in queue.cards])


@router.post("/{deck_id}/cards/{card_id}/review", dependencies=[WRITE],
             summary="Grade a review of a card, and schedule its next one",
             description="Spaced repetition as in Anki: `again` brings the card back in ten "
                         "minutes, the other grades in days that grow with each good review.",
             responses=error_responses(*NOT_FOUND, CardNotFound))
async def review_card(project_id: ProjectId, deck_id: DeckIdPath, card_id: CardIdPath,
                      request: ReviewRequest, service: DeckServiceDep) -> CardResponse:
    card = await service.review(project_id, str(deck_id), str(card_id), request.grade)
    return CardResponse(**_card_fields(card))


@router.get("/{deck_id}/anki", dependencies=[READ], response_class=PlainTextResponse,
            summary="Export a deck for Anki",
            description="A text file to import in Anki (File > Import): one Basic note per "
                        "card, into a deck of the same name, tagged `ragolex` and the "
                        "project's name, with the document and page each card comes from.",
            responses={200: {"content": {"text/plain": {}}}, **error_responses(*NOT_FOUND)})
async def export_anki(project_id: ProjectId, deck_id: DeckIdPath,
                      service: DeckServiceDep) -> PlainTextResponse:
    deck, text = await service.export_anki(project_id, str(deck_id))
    filename = "".join(char if (char.isascii() and char.isalnum()) or char in "-_" else "-"
                       for char in deck.name)
    return PlainTextResponse(text, headers={
        "Content-Disposition": f'attachment; filename="{filename.strip("-") or "deck"}.txt"'})
