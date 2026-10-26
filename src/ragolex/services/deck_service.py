"""Decks of flashcards: saved from study material, reviewed by spaced repetition, exported to Anki."""

import html
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from ragolex.core.errors import CardNotFound, DeckFull, DeckNotFound, ProjectNotFound
from ragolex.core.spaced_repetition import next_schedule
from ragolex.domain.models import Card, CardSource, Deck, Project, ReviewGrade
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.project_service import Page

# Cards a deck holds at most.
MAX_CARDS = 2000


@dataclass(frozen=True)
class NewCard:
    front: str
    back: str
    source: CardSource = CardSource()


@dataclass(frozen=True)
class ReviewQueue:
    """The deck and its cards due now, the longest due first."""

    deck: Deck
    cards: list[Card]


class DeckService:

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project

    async def _deck(self, project_name: str, deck_id: str) -> Deck:
        deck = await self.uow.decks.get((await self._project(project_name)).id, deck_id)
        if deck is None:
            raise DeckNotFound()
        return deck

    async def create(self, project_name: str, name: str, cards: Sequence[NewCard]) -> Deck:
        """A deck of ``cards``, all new and due now; the project is created if it is new."""
        project = await self.uow.projects.get_or_create(project_name)
        deck = await self.uow.decks.create(deck_id=str(uuid.uuid4()), project_id=project.id,
                                           name=name)
        await self.uow.decks.add_cards(deck.id, [(card.front, card.back, card.source)
                                                 for card in cards])
        await self.uow.commit()
        return await self._deck(project_name, deck.id)

    async def add_cards(self, project_name: str, deck_id: str, cards: Sequence[NewCard]) -> Deck:
        deck = await self._deck(project_name, deck_id)
        if deck.cards + len(cards) > MAX_CARDS:
            raise DeckFull(f"A deck holds at most {MAX_CARDS} cards")
        await self.uow.decks.add_cards(deck.id, [(card.front, card.back, card.source)
                                                 for card in cards])
        await self.uow.commit()
        return await self._deck(project_name, deck_id)

    async def list(self, project_name: str) -> list[Deck]:
        return await self.uow.decks.list_for_project((await self._project(project_name)).id)

    async def get(self, project_name: str, deck_id: str) -> Deck:
        return await self._deck(project_name, deck_id)

    async def cards(self, project_name: str, deck_id: str, *, offset: int,
                    limit: int) -> Page[Card]:
        deck = await self._deck(project_name, deck_id)
        return Page(items=await self.uow.decks.list_cards(deck.id, offset=offset, limit=limit),
                    total=deck.cards, offset=offset, limit=limit)

    async def delete(self, project_name: str, deck_id: str) -> None:
        if not await self.uow.decks.delete((await self._project(project_name)).id, deck_id):
            raise DeckNotFound()
        await self.uow.commit()

    async def due(self, project_name: str, deck_id: str, limit: int) -> ReviewQueue:
        deck = await self._deck(project_name, deck_id)
        return ReviewQueue(deck=deck, cards=await self.uow.decks.due_cards(deck.id, limit=limit))

    async def review(self, project_name: str, deck_id: str, card_id: str,
                     grade: ReviewGrade) -> Card:
        """Schedule the card's next review from how well it was remembered."""
        deck = await self._deck(project_name, deck_id)
        card = await self.uow.decks.get_card(deck.id, card_id)
        if card is None:
            raise CardNotFound()
        reviewed = await self.uow.decks.schedule_card(deck.id, card.id,
                                                      next_schedule(card.schedule, grade))
        if reviewed is None:  # Deleted meanwhile.
            raise CardNotFound()
        await self.uow.commit()
        return reviewed

    async def export_anki(self, project_name: str, deck_id: str) -> tuple[Deck, str]:
        """The deck as a text file that Anki imports (File > Import), with its name and tags."""
        deck = await self._deck(project_name, deck_id)
        cards = await self.uow.decks.list_cards(deck.id, offset=0, limit=MAX_CARDS)
        names = {}
        for key in sorted({card.source.file_key for card in cards if card.source.file_key}):
            record = await self.uow.files.get_by_key(deck.project_id, key)
            if record is not None:
                names[key] = record.original_name
        return deck, anki_text(deck.name, project_name, cards, names)


def anki_text(deck_name: str, project: str, cards: Sequence[Card],
              file_names: dict[str, str]) -> str:
    """Anki's text import format: tab-separated notes, with headers that set it up."""
    tags = f"ragolex {_tag(project)}"
    lines = ["#separator:tab", "#html:true", "#notetype:Basic", f"#deck:{_header(deck_name)}",
             "#tags column:3"]
    for card in cards:
        back = _html(card.back)
        where = _where(card.source, file_names)
        if where:
            back += f'<br><br><small>{html.escape(where)}</small>'
        lines.append(f"{_html(card.front)}\t{back}\t{tags}")
    return "\n".join(lines) + "\n"


def _html(text: str) -> str:
    return html.escape(text.replace("\t", " ")).replace("\r\n", "\n").replace("\n", "<br>")


def _header(text: str) -> str:
    return " ".join(text.split())


def _tag(text: str) -> str:
    return re.sub(r"[^\w-]+", "_", text).strip("_") or "project"


def _where(source: CardSource, file_names: dict[str, str]) -> str:
    if not source.file_key:
        return ""
    parts = [file_names.get(source.file_key, source.file_key)]
    if source.page is not None:
        parts.append(f"p. {source.page}")
    elif source.section:
        parts.append(source.section)
    return ", ".join(parts)
