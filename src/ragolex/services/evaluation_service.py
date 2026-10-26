import time
from dataclasses import dataclass, field

from ragolex.domain.llm import LLM, TokenPrices, TokenUsage
from ragolex.domain.repositories import UnitOfWork
from ragolex.evaluation.answers import AnswerResult, CitedSource
from ragolex.evaluation.dataset import Case, Dataset
from ragolex.evaluation.metrics import CaseResult, judge, matches
from ragolex.prompts.judge import JUDGE_PROMPT, JudgedSource, JudgePrompt
from ragolex.services.answer_service import Answer, AnswerService
from ragolex.services.indexing_service import IndexingService
from ragolex.services.processing_service import ProcessingService
from ragolex.services.search_service import SearchService
from ragolex.services.upload_service import UploadService

# What the judge is told when the documents do not answer a question.
NO_REFERENCE = "The documents do not answer this question."


@dataclass(frozen=True)
class AnswerSettings:
    """How answers are evaluated: written by ``answers``, graded by ``judge``."""

    answers: AnswerService
    judge: LLM
    min_score: float
    judge_prompt: JudgePrompt = JUDGE_PROMPT
    # The judge's prices, for the cost of grading; None leaves it unknown.
    judge_prices: TokenPrices | None = None


@dataclass(frozen=True)
class Usage:
    """Tokens of all answers, or of all grading; unknown when any call did not report them."""

    input_tokens: int | None = 0
    output_tokens: int | None = 0
    cost_usd: float | None = 0.0

    def add(self, usage: TokenUsage | None, cost: float | None) -> "Usage":
        if usage is None or self.input_tokens is None or self.output_tokens is None:
            return Usage(None, None, None)
        return Usage(self.input_tokens + usage.input_tokens,
                     self.output_tokens + usage.output_tokens,
                     None if cost is None or self.cost_usd is None else self.cost_usd + cost)


@dataclass(frozen=True)
class EvaluationRun:
    results: list[CaseResult]
    chunks: int
    seconds: dict[str, float]
    # Only when answers were evaluated.
    answers: list[AnswerResult] = field(default_factory=list)
    answer_usage: Usage | None = None
    judge_usage: Usage | None = None


class _Bytes:
    """An in-memory file to upload."""

    def __init__(self, data: bytes):
        self.data = data

    async def read(self, size: int = -1) -> bytes:
        size = len(self.data) if size < 0 else size
        piece, self.data = self.data[:size], self.data[size:]
        return piece


def project_name(dataset: Dataset) -> str:
    """The project a dataset is evaluated in.

    The dots keep it apart from every project created through the API,
    whose names cannot contain them.
    """
    return f"eval.{dataset.name}.{dataset.version}"


class EvaluationService:
    """Measures retrieval, and optionally answers, through the same steps as the API.

    The documents are uploaded, split, indexed and searched in a project of
    their own, which is deleted afterwards, also when the run fails. Their
    files stay in the upload service's storage; `ragolex eval` gives it a
    temporary folder.
    """

    def __init__(self, uow: UnitOfWork, upload: UploadService, processing: ProcessingService,
                 indexing: IndexingService, search: SearchService):
        self.uow = uow
        self.upload = upload
        self.processing = processing
        self.indexing = indexing
        self.search = search

    async def run(self, dataset: Dataset, *, top_k: int, chunk_size: int, overlap_size: int,
                  answers: AnswerSettings | None = None) -> EvaluationRun:
        project = project_name(dataset)
        # A run that was killed may have left its project behind.
        await self._delete(project)
        try:
            started = time.perf_counter()
            names: dict[str, str] = {}
            chunks = 0
            for document in dataset.documents:
                key = (await self.upload.save(project, document.name, document.content_type,
                                              _Bytes(document.path.read_bytes()))).file_id
                names[key] = document.name
                chunks += await self.processing.process(project, key, chunk_size=chunk_size,
                                                        overlap_size=overlap_size)
            processed = time.perf_counter()
            await self.indexing.index(project)
            indexed = time.perf_counter()

            results = []
            for case in dataset.cases:
                # Every result counts, however low it scores: the metrics apply
                # the minimum score themselves.
                hits = await self.search.search(project, case.question, top_k=top_k)
                results.append(judge(case, [(names[hit.file_key], hit) for hit in hits]))
            searched = time.perf_counter()
            seconds = {"processing": processed - started, "indexing": indexed - processed,
                       "search": searched - indexed}

            run = EvaluationRun(results=results, chunks=chunks, seconds=seconds)
            if answers is not None:
                run = await self._answer(run, dataset, project, names, top_k, answers)
                seconds["answers"] = time.perf_counter() - searched
        finally:
            await self.uow.rollback()
            await self._delete(project)
        return run

    async def _answer(self, run: EvaluationRun, dataset: Dataset, project: str,
                      names: dict[str, str], top_k: int,
                      settings: AnswerSettings) -> EvaluationRun:
        graded = []
        answer_usage, judge_usage = Usage(), Usage()
        for case in dataset.cases:
            answer = await settings.answers.ask(project, case.question, top_k=top_k,
                                                min_score=settings.min_score)
            answer_usage = answer_usage.add(answer.usage, answer.cost_usd)
            result = _answer_result(case, answer, names)
            if result.answered:
                result, usage = await self._grade(result, answer, settings)
                prices = settings.judge_prices
                judge_usage = judge_usage.add(usage, prices.cost(usage) if prices and usage else None)
            graded.append(result)
        return EvaluationRun(results=run.results, chunks=run.chunks, seconds=run.seconds,
                             answers=graded, answer_usage=answer_usage, judge_usage=judge_usage)

    @staticmethod
    async def _grade(result: AnswerResult, answer: Answer,
                     settings: AnswerSettings) -> tuple[AnswerResult, TokenUsage | None]:
        prompt = settings.judge_prompt
        completion = await settings.judge.complete(prompt.messages(
            question=result.case.question,
            reference=result.case.reference_answer or NO_REFERENCE,
            answer=result.text or "",
            sources=[JudgedSource(citation.number, citation.source.chunk.text)
                     for citation in answer.citations]))
        verdict = prompt.parse(completion.text)
        graded = AnswerResult(case=result.case, text=result.text, citations=result.citations,
                              grounded=verdict.grounded,
                              correct=verdict.correct if result.case.answerable else None,
                              reason=verdict.reason)
        return graded, completion.usage

    async def _delete(self, project: str) -> None:
        if await self.uow.projects.delete(project):
            await self.uow.commit()


def _answer_result(case: Case, answer: Answer, names: dict[str, str]) -> AnswerResult:
    citations = []
    for citation in answer.citations:
        file = names[citation.source.file_key]
        citations.append(CitedSource(
            number=citation.number, file=file, chunk_index=citation.source.chunk.index,
            relevant=bool(matches(case, file, citation.source.chunk.text))))
    return AnswerResult(case=case, text=answer.text, citations=tuple(citations))
