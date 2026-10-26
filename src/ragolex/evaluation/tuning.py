"""Comparing how a dataset is retrieved with different chunking: `ragolex tune`.

Each trial is one evaluation run with a chunk size and an overlap. Trials
are ranked by hit rate (does search find a relevant passage at all), then
MRR (how high), then recall; between equals, fewer chunks win, since they
cost less to embed and store.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Trial:
    chunk_size: int
    overlap_size: int
    hit_rate: float | None
    recall: float | None
    mrr: float | None
    above_min_score: float | None
    rejected: float | None
    chunks: int
    indexing_seconds: float
    # The lowest min score that keeps the answerable questions and turns
    # away the others, when one does; see the evaluation report.
    suggested_min_score: float | None

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "Trial":
        """The trial an evaluation report (see report.build_report) measured."""
        parameters, metrics = report["parameters"], report["metrics"]
        suggestion = report.get("suggested_min_score")
        return cls(chunk_size=parameters["chunk_size"], overlap_size=parameters["overlap_size"],
                   hit_rate=metrics["hit_rate"], recall=metrics["recall"], mrr=metrics["mrr"],
                   above_min_score=metrics["above_min_score"], rejected=metrics["rejected"],
                   chunks=report["dataset"]["chunks"],
                   indexing_seconds=report["seconds"]["indexing"],
                   suggested_min_score=suggestion["min_score"] if suggestion else None)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def grid(chunk_sizes: Sequence[int], overlaps: Sequence[int]) -> list[tuple[int, int]]:
    """Every chunk size with every overlap smaller than it, smallest first."""
    return [(size, overlap) for size in sorted(set(chunk_sizes))
            for overlap in sorted(set(overlaps)) if overlap < size]


def rank(trials: Sequence[Trial]) -> list[Trial]:
    """The trials, best first."""
    def key(trial: Trial) -> tuple[float, float, float, int]:
        return (-(trial.hit_rate or 0), -(trial.mrr or 0), -(trial.recall or 0), trial.chunks)
    return sorted(trials, key=key)
