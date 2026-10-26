"""Evaluation reports, and how they compare with a baseline.

A report is plain JSON: the run's parameters, its metrics overall and per
tag, and every question with what search returned. A baseline keeps only
the parameters and the metrics that must not get worse.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .answers import AnswerResult, answer_metrics
from .dataset import Dataset
from .metrics import CaseResult, metrics_by_tag, retrieval_metrics, suggest_min_score

# The metrics a change must not lower.
GATED_METRICS = ("hit_rate", "recall", "mrr", "above_min_score", "rejected")

# Metrics are only comparable between runs with the same parameters.
COMPARED_PARAMETERS = ("dataset", "embedding_model", "embedding_dimensions", "search_mode",
                       "reranker", "top_k", "chunk_size", "overlap_size", "min_score")


class BaselineMismatch(ValueError):
    """The baseline was measured with other parameters, so it cannot be compared."""


def build_report(*, dataset: Dataset, parameters: dict, results: Sequence[CaseResult],
                 chunks: int, seconds: dict[str, float], version: str) -> dict:
    min_score = parameters["min_score"]
    suggestion = suggest_min_score(results)
    return {
        "ragolex_version": version,
        "dataset": {"name": dataset.name, "version": dataset.version,
                    "documents": len(dataset.documents), "cases": len(dataset.cases),
                    "chunks": chunks},
        "parameters": parameters,
        "metrics": retrieval_metrics(results, min_score).as_dict(),
        "metrics_by_tag": {tag: metrics.as_dict()
                           for tag, metrics in metrics_by_tag(results, min_score).items()},
        "suggested_min_score": suggestion and {
            "min_score": suggestion.min_score, "above_min_score": suggestion.above_min_score,
            "rejected": suggestion.rejected},
        "seconds": {name: round(value, 2) for name, value in seconds.items()},
        "cases": [_case(result) for result in results],
    }


def _case(result: CaseResult) -> dict:
    first = result.first_relevant
    return {
        "id": result.case.id,
        "question": result.case.question,
        "tags": list(result.case.tags),
        "answerable": result.case.answerable,
        "first_relevant_rank": first.rank if first else None,
        "found": f"{len(result.found)}/{len(result.case.expected_sources)}",
        "results": [{"rank": hit.rank, "file": hit.file, "chunk_index": hit.chunk_index,
                     "page": hit.page, "score": round(hit.score, 4), "relevant": hit.relevant}
                    for hit in result.results],
    }


def add_answers(report: dict, results: Sequence[AnswerResult], parameters: dict,
                usage: dict) -> dict:
    """Adds the answers, their grades and their metrics to a retrieval report.

    Answer metrics are reported, not gated: they depend on the language
    model and the judge, which CI does not run.
    """
    report["answer_parameters"] = parameters
    report["answer_metrics"] = answer_metrics(results).as_dict()
    report["answer_usage"] = usage
    by_id = {result.case.id: result for result in results}
    for case in report["cases"]:
        result = by_id.get(case["id"])
        if result is not None:
            case["answer"] = {
                "text": result.text,
                "citations": [{"number": c.number, "file": c.file, "chunk_index": c.chunk_index,
                               "relevant": c.relevant} for c in result.citations],
                "grounded": result.grounded,
                "correct": result.correct,
                "reason": result.reason,
                "resisted": result.resisted,
            }
    return report


def baseline_from(report: dict) -> dict:
    return {"parameters": {name: report["parameters"][name] for name in COMPARED_PARAMETERS},
            "metrics": {name: report["metrics"][name] for name in GATED_METRICS}}


@dataclass(frozen=True)
class Comparison:
    metric: str
    baseline: float
    current: float

    @property
    def change(self) -> float:
        return round(self.current - self.baseline, 4)


def compare(report: dict, baseline: dict) -> list[Comparison]:
    """Each gated metric next to its baseline value.

    Raises BaselineMismatch when the parameters differ, or when a metric
    the baseline has cannot be measured any more.
    """
    different = [f"{name}: {baseline['parameters'].get(name)!r} in the baseline, "
                 f"{report['parameters'].get(name)!r} now"
                 for name in COMPARED_PARAMETERS
                 if baseline["parameters"].get(name) != report["parameters"].get(name)]
    if different:
        raise BaselineMismatch("The baseline was measured with other parameters ("
                               + "; ".join(different) + ").")
    comparisons = []
    for name in GATED_METRICS:
        expected, current = baseline["metrics"].get(name), report["metrics"].get(name)
        if expected is None:
            continue
        if current is None:
            raise BaselineMismatch(f"The baseline has {name}, which this dataset cannot measure.")
        comparisons.append(Comparison(metric=name, baseline=expected, current=current))
    return comparisons
