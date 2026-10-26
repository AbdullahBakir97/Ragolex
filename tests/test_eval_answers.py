import pytest

from ragolex.evaluation.answers import AnswerResult, CitedSource, answer_metrics
from ragolex.evaluation.dataset import Case, ExpectedSource


def case(case_id, answerable=True):
    sources = (ExpectedSource("a.txt", "alpha"),) if answerable else ()
    return Case(id=case_id, question="?", tags=(), expected_sources=sources,
                reference_answer="Alpha." if answerable else None)


def cited(*relevant):
    return tuple(CitedSource(number=i, file="a.txt", chunk_index=i, relevant=flag)
                 for i, flag in enumerate(relevant, start=1))


def test_answer_metrics():
    results = [
        AnswerResult(case("right"), "Alpha [1][2].", cited(True, False), grounded=1.0, correct=1.0),
        AnswerResult(case("half"), "Beta [1].", cited(False), grounded=0.5, correct=0.5),
        AnswerResult(case("silent"), None, ()),
        AnswerResult(case("unjudged"), "Alpha [1].", cited(True)),
        AnswerResult(case("none", answerable=False), None, ()),
        AnswerResult(case("made-up", answerable=False), "Gamma.", (), grounded=0.0),
    ]

    metrics = answer_metrics(results)

    assert (metrics.answerable, metrics.unanswerable) == (4, 2)
    assert metrics.answered == 0.75
    assert metrics.abstained == 0.5
    # Of the four citations of answered answerable questions, two are relevant.
    assert metrics.citation_precision == 0.5
    assert metrics.cites_expected == pytest.approx(2 / 3)
    assert metrics.grounded == 0.5
    # The unanswered question counts as wrong; the unjudged one is left out.
    assert metrics.correct == 0.5
    assert metrics.unjudged == 1


def test_metrics_without_answers_are_unknown():
    metrics = answer_metrics([AnswerResult(case("silent"), None, ())])

    assert (metrics.citation_precision, metrics.cites_expected, metrics.grounded) == (None,) * 3
    assert metrics.correct == 0.0
    assert metrics.abstained is None
