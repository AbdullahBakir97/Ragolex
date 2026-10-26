from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from ragolex.core.errors import ConversationNotFound, ProjectNotFound
from ragolex.core.metrics import ANSWERS, LLM_COST, LLM_TOKENS
from ragolex.core.tracing import annotate, end_span, span, start_span
from ragolex.domain.llm import LLM, Message, TokenPrices, TokenUsage
from ragolex.domain.models import (
    AnswerRecord,
    Conversation,
    ConversationMessage,
    Project,
    ScoredChunk,
    SearchFilters,
    StoredCitation,
)
from ragolex.domain.repositories import UnitOfWork
from ragolex.prompts.answer import ANSWER_PROMPT, NO_ANSWER, AnswerPrompt
from ragolex.prompts.condense import CONDENSE_PROMPT, CondensePrompt
from ragolex.prompts.research import RESEARCH_PROMPT, ResearchPrompt
from ragolex.services.limit_service import LimitService
from ragolex.services.search_service import SearchService

# The usage of an answer for which the model was not called.
NOT_CALLED = TokenUsage(input_tokens=0, output_tokens=0)

# Earlier messages of a conversation given to the model: the last three
# questions and their answers.
HISTORY_MESSAGES = 6

# Conversations are titled after their first question, shortened to this.
TITLE_LENGTH = 80

# Research mode: the most searches one planning or review step asks for.
MAX_QUERIES_PER_STEP = 4


@dataclass(frozen=True)
class SearchStep:
    """One search of research mode: the query, and how many chunks it found."""

    query: str
    results: int


@dataclass(frozen=True)
class Citation:
    """A source the answer cites; ``number`` is its [n] marker in the answer."""

    number: int
    source: ScoredChunk


@dataclass(frozen=True)
class AnswerDelta:
    """The next piece of an answer's text, while the model is still writing it."""

    text: str


@dataclass(frozen=True)
class Answer:
    """``text`` is None when the project's documents do not answer the question.

    ``usage`` is None when the provider did not report it; ``cost_usd`` is
    None when the usage or the model's prices are unknown. In a
    conversation, ``search_question`` is the standalone question the answer
    was searched with, when it differs from the question asked, and
    ``message_id`` is the answer's message, which feedback refers to.
    """

    text: str | None
    citations: list[Citation]
    prompt_version: str
    usage: TokenUsage | None
    cost_usd: float | None
    conversation_id: str | None = None
    search_question: str | None = None
    message_id: int | None = None
    research: list[SearchStep] | None = None


@dataclass(frozen=True)
class Prepared:
    """A question ready to be answered: its sources, and its conversation if any.

    ``search_question`` is the standalone question the sources were searched
    with; ``usage`` is what rewriting the question into it cost (NOT_CALLED
    when it needed no rewriting).
    """

    project: Project
    question: str
    search_question: str
    sources: list[ScoredChunk]
    conversation: Conversation | None
    history: list[Message]
    usage: TokenUsage | None
    research: list[SearchStep] | None = None


class AnswerService:
    """Answers a question from a project's documents, citing its sources.

    Every answer is recorded with its token usage and cost; the question
    and the answer text are not. In a conversation, the question and the
    answer are kept as messages of the conversation, and a follow-up
    question is first rewritten into one that can be searched on its own.
    """

    def __init__(self, search: SearchService, llm: LLM, uow: UnitOfWork, min_score: float,
                 prices: TokenPrices | None = None, prompt: AnswerPrompt = ANSWER_PROMPT,
                 condense_prompt: CondensePrompt = CONDENSE_PROMPT,
                 research_prompt: ResearchPrompt = RESEARCH_PROMPT, max_research_steps: int = 3,
                 limits: LimitService | None = None):
        self.search = search
        self.llm = llm
        self.uow = uow
        self.min_score = min_score
        self.prices = prices
        self.prompt = prompt
        self.condense_prompt = condense_prompt
        self.research_prompt = research_prompt
        self.max_research_steps = max_research_steps
        # Sends the tenant's budget alerts as answers cost money.
        self.limits = limits

    async def ask(self, project_name: str, question: str, top_k: int,
                  min_score: float | None = None, conversation_id: str | None = None,
                  filters: SearchFilters | None = None, research_steps: int = 0) -> Answer:
        """Retrieve the best matching chunks and have the model answer from them.

        Only chunks scoring at least ``min_score`` (default: the service's)
        are used. Without any, or when the model finds no answer in them,
        the answer has no text, and without any the model is not called for
        the answer. With ``conversation_id``, the answer follows on from
        that conversation and is added to it.
        """
        prepared = await self.prepare(project_name, question, top_k, min_score, conversation_id,
                                      filters, research_steps)
        if not prepared.sources:
            answer = self._no_answer(prepared, NOT_CALLED)
        else:
            with span("answer.generate", model=self.llm.model, sources=len(prepared.sources),
                      prompt_version=self.prompt.version) as current:
                completion = await self.llm.complete(self._answer_messages(prepared))
                annotate(current, **_usage_attributes(completion.usage))
            answer = self._finish(prepared, completion.text, completion.usage)
        return await self._record(prepared, answer, streamed=False)

    async def prepare(self, project_name: str, question: str, top_k: int,
                      min_score: float | None = None,
                      conversation_id: str | None = None,
                      filters: SearchFilters | None = None,
                      research_steps: int = 0) -> Prepared:
        """Find the sources for ``question``, rewriting a follow-up first.

        With ``research_steps`` (research mode), the model plans the
        searches, and reviews what they found up to that many times (at most
        the service's ``max_research_steps``); see ``_research``. Raises
        ConversationNotFound for a conversation that is not this project's.
        """
        project = await self.uow.projects.get_by_name(project_name)
        if project is None:
            raise ProjectNotFound()
        conversation = None
        history: list[Message] = []
        if conversation_id is not None:
            conversation = await self.uow.conversations.get(project.id, conversation_id)
            if conversation is None:
                raise ConversationNotFound()
            stored = await self.uow.conversations.messages(conversation.id, last=HISTORY_MESSAGES)
            history = [Message(message.role, message.content or NO_ANSWER) for message in stored]

        search_question = question
        usage: TokenUsage | None = NOT_CALLED
        if history:
            with span("answer.condense", model=self.llm.model, history=len(history)):
                completion = await self.llm.complete(
                    self.condense_prompt.messages(history, question))
            search_question = self.condense_prompt.standalone(completion.text, question)
            usage = completion.usage

        if min_score is None:
            min_score = self.min_score
        research = None
        if research_steps > 0:
            sources, research, research_usage = await self._research(
                project_name, search_question, top_k, min_score, filters,
                min(research_steps, self.max_research_steps))
            usage = _add(usage, research_usage)
        else:
            sources = await self.search.search(project_name, search_question, top_k=top_k,
                                               min_score=min_score, filters=filters)
        return Prepared(project=project, question=question, search_question=search_question,
                        sources=sources, conversation=conversation, history=history, usage=usage,
                        research=research)

    async def _research(self, project_name: str, question: str, top_k: int, min_score: float,
                        filters: SearchFilters | None,
                        steps: int) -> tuple[list[ScoredChunk], list[SearchStep],
                                             TokenUsage | None]:
        """Search in up to ``steps`` rounds, each planned or reviewed by the model.

        The first round searches what the model plans (the question itself
        when the plan is unreadable); each later one searches only what the
        review of the sources so far says is still missing, and none
        follows when nothing is. The sources are each search's best ones
        taken in turn, so every part of the question has its own, up to
        ``top_k`` in all.
        """
        usage: TokenUsage | None = NOT_CALLED
        results: list[list[ScoredChunk]] = []
        trail: list[SearchStep] = []
        searched: set[str] = set()
        sources: list[ScoredChunk] = []
        for step in range(steps):
            if step == 0:
                messages = self.research_prompt.plan_messages(question, MAX_QUERIES_PER_STEP)
            else:
                messages = self.research_prompt.review_messages(
                    question, [s.query for s in trail], sources, MAX_QUERIES_PER_STEP)
            completion = await self.llm.complete(messages)
            usage = _add(usage, completion.usage)
            queries = [query for query in self.research_prompt.queries(
                completion.text, MAX_QUERIES_PER_STEP) if query.lower() not in searched]
            if step == 0 and not queries:
                queries = [question]
            if not queries:
                break
            for query in queries:
                searched.add(query.lower())
                hits = await self.search.search(project_name, query, top_k=top_k,
                                                min_score=min_score, filters=filters)
                trail.append(SearchStep(query=query, results=len(hits)))
                results.append(hits)
            sources = _interleave(results, top_k)
        return sources, trail, usage

    async def stream(self, prepared: Prepared) -> AsyncIterator[AnswerDelta | Answer]:
        """Like ``ask``, for a prepared question: the text as it is written, then the Answer.

        Text is held back while the reply may still be the model's no-answer
        reply, so a client never shows it; that reply yields no deltas. The
        answer is recorded, and added to its conversation, only when the
        stream completes.
        """
        if not prepared.sources:
            answer = self._no_answer(prepared, NOT_CALLED)
        else:
            reply = ""
            usage = None
            holding = True
            # Not made current: the stream yields to its reader between pieces.
            generation = start_span("answer.generate", model=self.llm.model, streamed=True,
                                    sources=len(prepared.sources),
                                    prompt_version=self.prompt.version)
            try:
                async for piece in self.llm.stream(self._answer_messages(prepared)):
                    if isinstance(piece, TokenUsage):
                        usage = piece
                        continue
                    reply += piece
                    if holding and self.prompt.could_be_no_answer(reply):
                        continue
                    yield AnswerDelta(reply if holding else piece)
                    holding = False
            finally:
                end_span(generation, **_usage_attributes(usage))
            answer = self._finish(prepared, reply, usage)
        yield await self._record(prepared, answer, streamed=True)

    def _answer_messages(self, prepared: Prepared) -> list[Message]:
        return self.prompt.messages(prepared.search_question, prepared.sources, prepared.history,
                                    assistant_name=prepared.project.assistant_name,
                                    instructions=prepared.project.instructions)

    def _finish(self, prepared: Prepared, reply: str, usage: TokenUsage | None) -> Answer:
        if self.prompt.is_no_answer(reply):
            return self._no_answer(prepared, usage)
        # The model may cite numbers that were never given; those are dropped.
        sources = prepared.sources
        citations = [Citation(number=number, source=sources[number - 1])
                     for number in self.prompt.cited_numbers(reply)
                     if 1 <= number <= len(sources)]
        return self._answer(prepared, reply.strip(), citations, usage)

    def _no_answer(self, prepared: Prepared, usage: TokenUsage | None) -> Answer:
        return self._answer(prepared, None, [], usage)

    def _answer(self, prepared: Prepared, text: str | None, citations: list[Citation],
                usage: TokenUsage | None) -> Answer:
        # Rewriting a follow-up is part of the answer's cost.
        total = _add(prepared.usage, usage)
        rewritten = prepared.search_question != prepared.question
        return Answer(text=text, citations=citations, prompt_version=self.prompt.version,
                      usage=total, cost_usd=self._cost(total),
                      conversation_id=prepared.conversation.id if prepared.conversation else None,
                      search_question=prepared.search_question if rewritten else None,
                      research=prepared.research)

    def _cost(self, usage: TokenUsage | None) -> float | None:
        if usage == NOT_CALLED:
            return 0.0
        if usage is None or self.prices is None:
            return None
        return self.prices.cost(usage)

    async def _record(self, prepared: Prepared, answer: Answer, *, streamed: bool) -> Answer:
        model_called = answer.usage != NOT_CALLED
        await self.uow.answers.add(AnswerRecord(
            project_id=prepared.project.id, prompt_version=answer.prompt_version,
            model=self.llm.model if model_called else None, streamed=streamed,
            answered=answer.text is not None,
            input_tokens=answer.usage.input_tokens if answer.usage else None,
            output_tokens=answer.usage.output_tokens if answer.usage else None,
            cost_usd=answer.cost_usd))
        conversation = prepared.conversation
        if conversation is not None:
            _, message_id = await self.uow.conversations.add_messages(conversation.id, [
                ConversationMessage(role="user", content=prepared.question),
                ConversationMessage(
                    role="assistant", content=answer.text,
                    citations=[_stored(citation) for citation in answer.citations],
                    prompt_version=answer.prompt_version,
                    search_question=answer.search_question),
            ], title=None if conversation.title else _title(prepared.question))
            answer = replace(answer, message_id=message_id)
        if self.limits is not None and answer.cost_usd:
            await self.limits.note_spending(prepared.project)
        await self.uow.commit()
        ANSWERS.labels(answered=str(answer.text is not None).lower()).inc()
        if model_called and answer.usage:
            LLM_TOKENS.labels(kind="input").inc(answer.usage.input_tokens)
            LLM_TOKENS.labels(kind="output").inc(answer.usage.output_tokens)
        if answer.cost_usd:
            LLM_COST.inc(answer.cost_usd)
        return answer


def _interleave(results: list[list[ScoredChunk]], limit: int) -> list[ScoredChunk]:
    """Each search's best chunk, then each one's second best, and so on, without repeats."""
    chosen: list[ScoredChunk] = []
    seen: set[tuple[str, int]] = set()
    for rank in range(max((len(hits) for hits in results), default=0)):
        for hits in results:
            if rank < len(hits):
                key = (hits[rank].file_key, hits[rank].chunk.index)
                if key not in seen:
                    seen.add(key)
                    chosen.append(hits[rank])
    return chosen[:limit]


def _add(first: TokenUsage | None, second: TokenUsage | None) -> TokenUsage | None:
    """Two usages together; unknown when either is."""
    if first is None or second is None:
        return None
    return TokenUsage(input_tokens=first.input_tokens + second.input_tokens,
                      output_tokens=first.output_tokens + second.output_tokens)


def _stored(citation: Citation) -> StoredCitation:
    source = citation.source
    return StoredCitation(number=citation.number, file_key=source.file_key,
                          chunk_index=source.chunk.index, page=source.chunk.metadata.get("page"),
                          section=source.chunk.metadata.get("section"),
                          score=source.score, text=source.chunk.text)


def _title(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= TITLE_LENGTH else title[:TITLE_LENGTH - 1].rstrip() + "…"


def _usage_attributes(usage: TokenUsage | None) -> dict[str, int]:
    """A model call's token counts as span attributes, in OpenTelemetry's names."""
    if usage is None:
        return {}
    return {"gen_ai.usage.input_tokens": usage.input_tokens,
            "gen_ai.usage.output_tokens": usage.output_tokens}
