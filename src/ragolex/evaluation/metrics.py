"""Retrieval metrics: did search find the passages that answer each question?

For a question the documents answer, a retrieved chunk is relevant when it
comes from an expected file and contains that source's evidence. Over the
top k results:

- hit rate: share of questions with at least one relevant result;
- recall: share of each question's expected sources found, averaged;
- MRR: the mean of 1 / rank of the first relevant result (0 without one);
- above min score: share of questions whose first relevant result scores
  at least the minimum score, so an answer would be given from it.

For a question the documents do not answer, ``rejected`` is the share for
which no result reaches the minimum score, so the model is not even asked.
The minimum score trades these last two off; ``suggest_min_score`` finds
the value that serves both best.
"""

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

from ragolex.domain.models import ScoredChunk

from .dataset import Case


def normalize(text: str) -> str:
    """Case and line breaks do not matter when looking for evidence."""
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class Retrieved:
    """One search result; ``matches`` are the indexes of the expected sources it contains."""

    rank: int
    file: str
    chunk_index: int
    page: int | None
    score: float
    matches: tuple[int, ...]

    @property
    def relevant(self) -> bool:
        return bool(self.matches)


@dataclass(frozen=True)
class CaseResult:
    case: Case
    results: tuple[Retrieved, ...]

    @property
    def found(self) -> set[int]:
        """The expected sources among the results."""
        return {match for result in self.results for match in result.matches}

    @property
    def first_relevant(self) -> Retrieved | None:
        return next((result for result in self.results if result.relevant), None)

    @property
    def recall(self) -> float:
        return len(self.found) / len(self.case.expected_sources)

    @property
    def reciprocal_rank(self) -> float:
        first = self.first_relevant
        return 1 / first.rank if first else 0.0

    @property
    def best_score(self) -> float | None:
        return self.results[0].score if self.results else None


def matches(case: Case, file: str, text: str) -> tuple[int, ...]:
    """The indexes of the case's expected sources that a chunk of ``file`` contains."""
    text = normalize(text)
    return tuple(index for index, source in enumerate(case.expected_sources)
                 if source.file == file and normalize(source.evidence) in text)


def judge(case: Case, results: Sequence[tuple[str, ScoredChunk]]) -> CaseResult:
    """Mark which results are relevant; ``results`` pairs each hit with its document's name."""
    retrieved = []
    for rank, (file, hit) in enumerate(results, start=1):
        retrieved.append(Retrieved(rank=rank, file=file, chunk_index=hit.chunk.index,
                                   page=hit.chunk.metadata.get("page"), score=hit.score,
                                   matches=matches(case, file, hit.chunk.text)))
    return CaseResult(case=case, results=tuple(retrieved))


@dataclass(frozen=True)
class RetrievalMetrics:
    answerable: int
    unanswerable: int
    # None when there is no question of the kind they measure.
    hit_rate: float | None
    recall: float | None
    mrr: float | None
    above_min_score: float | None
    rejected: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return {name: (round(value, 4) if isinstance(value, float) else value)
                for name, value in asdict(self).items()}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _kept(result: CaseResult, min_score: float) -> bool:
    first = result.first_relevant
    return first is not None and first.score >= min_score


def _rejected(result: CaseResult, min_score: float) -> bool:
    best = result.best_score
    return best is None or best < min_score


def retrieval_metrics(results: Iterable[CaseResult], min_score: float) -> RetrievalMetrics:
    results = list(results)
    answerable = [result for result in results if result.case.answerable]
    unanswerable = [result for result in results if not result.case.answerable]
    return RetrievalMetrics(
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        hit_rate=_mean([float(result.first_relevant is not None) for result in answerable]),
        recall=_mean([result.recall for result in answerable]),
        mrr=_mean([result.reciprocal_rank for result in answerable]),
        above_min_score=_mean([float(_kept(result, min_score)) for result in answerable]),
        rejected=_mean([float(_rejected(result, min_score)) for result in unanswerable]),
    )


def metrics_by_tag(results: Iterable[CaseResult], min_score: float) -> dict[str, RetrievalMetrics]:
    results = list(results)
    tags = sorted({tag for result in results for tag in result.case.tags})
    return {tag: retrieval_metrics([result for result in results if tag in result.case.tags],
                                   min_score)
            for tag in tags}


@dataclass(frozen=True)
class MinScoreSuggestion:
    min_score: float
    above_min_score: float
    rejected: float


def suggest_min_score(results: Iterable[CaseResult]) -> MinScoreSuggestion | None:
    """The minimum score that best keeps answerable questions and rejects the others.

    Both shares count equally. Among equally good values, the middle one is
    taken, as far from both kinds of question as the data allows. None
    without both kinds of question, or when no value does better than
    answering all of them or none.
    """
    results = list(results)
    answerable = [result for result in results if result.case.answerable]
    unanswerable = [result for result in results if not result.case.answerable]
    if not answerable or not unanswerable:
        return None

    def shares(threshold: float) -> tuple[float, float]:
        kept = sum(_kept(result, threshold) for result in answerable) / len(answerable)
        rejected = sum(_rejected(result, threshold) for result in unanswerable) / len(unanswerable)
        return kept, rejected

    # Only scores that occur can change the outcome; just above each also counts.
    scores = {round(hit.score, 3) for result in results for hit in result.results}
    candidates = sorted(scores | {round(score + 0.001, 3) for score in scores})
    balanced = {candidate: sum(shares(candidate)) / 2 for candidate in candidates}
    best = max(balanced.values())
    if best <= 0.5:
        return None
    tied = [candidate for candidate, value in balanced.items() if value == best]
    middle = round((tied[0] + tied[-1]) / 2, 3)
    chosen = middle if sum(shares(middle)) / 2 == best else tied[0]
    kept, rejected = shares(chosen)
    return MinScoreSuggestion(min_score=round(chosen, 3), above_min_score=round(kept, 4),
                              rejected=round(rejected, 4))
