import pytest

from ragolex.domain.models import Chunk, ScoredChunk
from ragolex.evaluation.dataset import Case, Dataset, ExpectedSource
from ragolex.evaluation.metrics import (
    judge,
    metrics_by_tag,
    retrieval_metrics,
    suggest_min_score,
)
from ragolex.evaluation.report import (
    BaselineMismatch,
    baseline_from,
    build_report,
    compare,
)


def case(case_id, *sources, tags=()):
    return Case(id=case_id, question=f"Question {case_id}?", tags=tags,
                expected_sources=tuple(ExpectedSource(file, evidence) for file, evidence in sources),
                reference_answer="An answer." if sources else None)


def hit(file, text, score, index=0, page=None):
    metadata = {"page": page} if page else {}
    return file, ScoredChunk(file_key=f"key_{file}", chunk=Chunk(index, text, metadata), score=score)


def test_a_result_is_relevant_when_its_file_and_evidence_match():
    expected = case("deploys", ("guide.txt", "never on Fridays after noon"))

    result = judge(expected, [
        hit("other.txt", "Never on Fridays after noon.", 0.9),
        hit("guide.txt", "Deploys happen on weekdays,\nnever on FRIDAYS after   noon.", 0.8, 3, 2),
    ])

    first, second = result.results
    assert (first.relevant, second.relevant) == (False, True)
    assert (second.rank, second.chunk_index, second.page) == (2, 3, 2)
    assert result.reciprocal_rank == 0.5
    assert result.recall == 1.0


def test_recall_counts_each_expected_source():
    expected = case("both", ("a.txt", "alpha"), ("b.txt", "beta"))

    result = judge(expected, [hit("a.txt", "alpha", 0.7), hit("a.txt", "alpha again", 0.6)])

    assert result.found == {0}
    assert result.recall == 0.5


def test_metrics_over_answerable_and_unanswerable_questions():
    results = [
        judge(case("first", ("a.txt", "alpha"), tags=("direct",)),
              [hit("a.txt", "alpha", 0.8)]),
        judge(case("second", ("a.txt", "beta"), tags=("paraphrase",)),
              [hit("a.txt", "other", 0.6), hit("a.txt", "beta", 0.4)]),
        judge(case("missed", ("a.txt", "gamma"), tags=("paraphrase",)),
              [hit("a.txt", "other", 0.5)]),
        judge(case("none", tags=("unanswerable",)), [hit("a.txt", "alpha", 0.45)]),
        judge(case("nothing", tags=("unanswerable",)), []),
    ]

    metrics = retrieval_metrics(results, min_score=0.5)

    assert (metrics.answerable, metrics.unanswerable) == (3, 2)
    assert metrics.hit_rate == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.mrr == pytest.approx((1 + 0.5 + 0) / 3)
    # "second" finds its source, but scoring 0.4 it would not be answered.
    assert metrics.above_min_score == pytest.approx(1 / 3)
    assert metrics.rejected == 1.0

    by_tag = metrics_by_tag(results, min_score=0.5)
    assert by_tag["paraphrase"].hit_rate == 0.5
    assert by_tag["unanswerable"].hit_rate is None


def test_suggests_the_min_score_between_both_kinds_of_question():
    results = [
        judge(case("a", ("a.txt", "alpha")), [hit("a.txt", "alpha", 0.80)]),
        judge(case("b", ("a.txt", "beta")), [hit("a.txt", "beta", 0.70)]),
        judge(case("c"), [hit("a.txt", "alpha", 0.60)]),
        judge(case("d"), [hit("a.txt", "alpha", 0.50)]),
    ]

    suggestion = suggest_min_score(results)

    assert 0.6 < suggestion.min_score <= 0.7
    assert (suggestion.above_min_score, suggestion.rejected) == (1.0, 1.0)
    assert suggest_min_score(results[:2]) is None


def test_suggests_no_min_score_when_none_separates_the_questions():
    results = [
        judge(case("a", ("a.txt", "alpha")), [hit("a.txt", "alpha", 0.50)]),
        judge(case("b"), [hit("a.txt", "alpha", 0.80)]),
    ]

    assert suggest_min_score(results) is None


def report_for(results, **parameters):
    dataset = Dataset(name="tiny", version="v1", description="", documents=(),
                      cases=tuple(result.case for result in results))
    return build_report(dataset=dataset, results=results, chunks=3, version="1.0",
                        seconds={"processing": 0.1, "indexing": 0.2, "search": 0.3},
                        parameters={"dataset": "tiny/v1", "embedding_model": "m",
                                    "embedding_dimensions": 8, "search_mode": "hybrid", "reranker": None, "top_k": 5, "chunk_size": 1000,
                                    "overlap_size": 200, "min_score": 0.5, **parameters})


RESULTS = [judge(case("a", ("a.txt", "alpha"), tags=("direct",)),
                 [hit("a.txt", "x", 0.9), hit("a.txt", "alpha", 0.8)]),
           judge(case("z", tags=("unanswerable",)), [hit("a.txt", "x", 0.3)])]


def test_the_report_lists_each_question_with_its_results():
    report = report_for(RESULTS)

    assert report["metrics"]["mrr"] == 0.5
    assert report["dataset"] == {"name": "tiny", "version": "v1", "documents": 0, "cases": 2,
                                 "chunks": 3}
    first = report["cases"][0]
    assert (first["first_relevant_rank"], first["found"]) == (2, "1/1")
    assert first["results"][1] == {"rank": 2, "file": "a.txt", "chunk_index": 0, "page": None,
                                   "score": 0.8, "relevant": True}
    assert set(report["metrics_by_tag"]) == {"direct", "unanswerable"}


def test_compares_the_gated_metrics_with_a_baseline():
    report = report_for(RESULTS)
    baseline = baseline_from(report)
    baseline["metrics"]["mrr"] = 0.75

    comparisons = {c.metric: c for c in compare(report, baseline)}

    assert set(comparisons) == {"hit_rate", "recall", "mrr", "above_min_score", "rejected"}
    assert comparisons["mrr"].change == -0.25
    assert comparisons["hit_rate"].change == 0


def test_a_baseline_with_other_parameters_cannot_be_compared():
    baseline = baseline_from(report_for(RESULTS, top_k=3))

    with pytest.raises(BaselineMismatch, match="top_k: 3 in the baseline, 5 now"):
        compare(report_for(RESULTS), baseline)


def test_a_baseline_metric_that_cannot_be_measured_is_a_mismatch():
    answerable_only = RESULTS[:1]
    baseline = baseline_from(report_for(RESULTS))

    with pytest.raises(BaselineMismatch, match="rejected"):
        compare(report_for(answerable_only), baseline)
