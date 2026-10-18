"""Study material from a document: a summary, flashcards or a quiz."""

from collections.abc import Sequence
from dataclasses import dataclass

from mini_rag.core.errors import FileNotFound, FileNotProcessed, ProjectNotFound
from mini_rag.core.metrics import LLM_COST, LLM_TOKENS
from mini_rag.domain.llm import LLM, TokenPrices, TokenUsage
from mini_rag.domain.models import AnswerRecord, Chunk, StudyItem, StudyKind
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.prompts.study import STUDY_PROMPTS, Passage

# Characters of the document given to the model by default: about 8,000 tokens.
MAX_CHARACTERS = 32_000


@dataclass(frozen=True)
class StudySource:
    """A passage of the document that items cite by ``number``."""

    number: int
    chunk_index: int
    page: int | None
    section: str | None
    text: str


@dataclass(frozen=True)
class StudyMaterial:
    """Items of one ``kind``, and the passages they cite.

    ``passages`` of the document's ``chunks`` were given to the model: all of
    them unless the document is longer than the model is given at once.
    """

    kind: StudyKind
    file_key: str
    original_name: str
    items: list[StudyItem]
    sources: list[StudySource]
    prompt_version: str
    usage: TokenUsage | None
    cost_usd: float | None
    passages: int
    chunks: int


class StudyService:
    """Asks the model for study material from one file's chunks."""

    def __init__(self, uow: UnitOfWork, llm: LLM, prices: TokenPrices | None = None,
                 max_characters: int = MAX_CHARACTERS):
        self.uow = uow
        self.llm = llm
        self.prices = prices
        self.max_characters = max_characters

    async def generate(self, project_name: str, file_key: str, kind: StudyKind,
                       count: int) -> StudyMaterial:
        """At most ``count`` items; fewer when the document has less to say.

        The model's call is recorded like an answer's, so it counts in the
        project's usage and the tenant's quota.
        """
        project = await self.uow.projects.get_by_name(project_name)
        if project is None:
            raise ProjectNotFound()
        record = await self.uow.files.get_by_key(project.id, file_key)
        if record is None:
            raise FileNotFound()
        total = await self.uow.chunks.count_for_file(record.id)
        if not total:
            raise FileNotProcessed()
        chunks = _spread(await self.uow.chunks.list_for_file(record.id, offset=0, limit=total),
                         self.max_characters)
        passages = [Passage(number, chunk.text, page=_page(chunk), section=_section(chunk))
                    for number, chunk in enumerate(chunks, start=1)]

        prompt = STUDY_PROMPTS[kind]
        completion = await self.llm.complete(
            prompt.messages(title=record.original_name, passages=passages, count=count))
        items = prompt.parse(completion.text, passages, count)
        cost = self.prices.cost(completion.usage) if completion.usage and self.prices else None
        await self.uow.answers.add(AnswerRecord(
            project_id=project.id, prompt_version=prompt.version, model=self.llm.model,
            streamed=False, answered=bool(items),
            input_tokens=completion.usage.input_tokens if completion.usage else None,
            output_tokens=completion.usage.output_tokens if completion.usage else None,
            cost_usd=cost))
        await self.uow.commit()
        if completion.usage:
            LLM_TOKENS.labels(kind="input").inc(completion.usage.input_tokens)
            LLM_TOKENS.labels(kind="output").inc(completion.usage.output_tokens)
        if cost:
            LLM_COST.inc(cost)

        cited = {number for item in items for number in item.sources}
        return StudyMaterial(
            kind=kind, file_key=file_key, original_name=record.original_name, items=items,
            sources=[StudySource(number, chunk.index, _page(chunk), _section(chunk), chunk.text)
                     for number, chunk in enumerate(chunks, start=1) if number in cited],
            prompt_version=prompt.version, usage=completion.usage, cost_usd=cost,
            passages=len(chunks), chunks=total)


def _spread(chunks: Sequence[Chunk], max_characters: int) -> list[Chunk]:
    """The chunks, or as many as fit spread evenly over the document, in order."""
    if sum(len(chunk.text) for chunk in chunks) <= max_characters:
        return list(chunks)
    average = sum(len(chunk.text) for chunk in chunks) / len(chunks)
    keep = max(1, int(max_characters // average))
    while keep > 1:
        step = len(chunks) / keep
        chosen = [chunks[int(position * step)] for position in range(keep)]
        if sum(len(chunk.text) for chunk in chosen) <= max_characters:
            return chosen
        keep -= 1
    return [chunks[0]]


def _page(chunk: Chunk) -> int | None:
    page = chunk.metadata.get("page")
    return page if isinstance(page, int) else None


def _section(chunk: Chunk) -> str | None:
    section = chunk.metadata.get("section")
    return section if isinstance(section, str) and section else None
