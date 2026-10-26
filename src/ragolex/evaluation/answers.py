"""Answer metrics: are the answers right, grounded and correctly cited?

Each question is answered as the API would answer it, and graded:

- answered: share of answerable questions that got an answer, not
  ``no_answer``;
- abstained: share of unanswerable questions answered with ``no_answer``;
- citation precision: share of all citations, over answered answerable
  questions, that point to a passage holding the expected evidence;
- cites expected: share of answered answerable questions citing at least
  one expected source;
- grounded: how far answers are supported by their sources (1 yes, 0.5
  partly, 0 no), averaged over every answer the judge graded;
- correct: how far answers say what the reference answer says, averaged
  over all answerable questions, a missing answer counting as 0.

The last two come from a language model acting as judge; the others are
counted from the citations.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .dataset import Case


@dataclass(frozen=True)
class CitedSource:
    number: int
    file: str
    chunk_index: int
    relevant: bool


@dataclass(frozen=True)
class AnswerResult:
    case: Case
    # None when the answer was no_answer.
    text: str | None
    citations: tuple[CitedSource, ...]
    # The judge's scores; None when it was not asked or gave no clear verdict.
    grounded: float | None = None
    correct: float | None = None
    reason: str = ""

    @property
    def answered(self) -> bool:
        return self.text is not None


@dataclass(frozen=True)
class AnswerMetrics:
    answerable: int
    unanswerable: int
    answered: float | None
    abstained: float | None
    citation_precision: float | None
    cites_expected: float | None
    grounded: float | None
    correct: float | None
    # Answers the judge gave no clear verdict on.
    unjudged: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {name: (round(value, 4) if isinstance(value, float) else value)
                for name, value in asdict(self).items()}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def answer_metrics(results: Iterable[AnswerResult]) -> AnswerMetrics:
    results = list(results)
    answerable = [result for result in results if result.case.answerable]
    unanswerable = [result for result in results if not result.case.answerable]
    answered = [result for result in answerable if result.answered]
    citations = [citation for result in answered for citation in result.citations]
    judged = [result for result in results if result.answered]
    return AnswerMetrics(
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        answered=_mean([float(result.answered) for result in answerable]),
        abstained=_mean([float(not result.answered) for result in unanswerable]),
        citation_precision=_mean([float(citation.relevant) for citation in citations]),
        cites_expected=_mean([float(any(c.relevant for c in result.citations))
                              for result in answered]),
        grounded=_mean([result.grounded for result in judged if result.grounded is not None]),
        # An unanswered question counts as wrong; an answer the judge did not grade, not at all.
        correct=_mean([result.correct if result.answered and result.correct is not None else 0.0
                       for result in answerable
                       if not result.answered or result.correct is not None]),
        unjudged=sum(1 for result in judged
                     if result.grounded is None
                     or (result.case.answerable and result.correct is None)),
    )
