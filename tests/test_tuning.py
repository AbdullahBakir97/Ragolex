"""`ragolex tune`: the retrieval evaluation with each chunk size and overlap, ranked."""

import json

import pytest

from ragolex import cli
from ragolex.domain.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE
from ragolex.evaluation.tuning import Trial, grid, rank

from .test_eval_command import (  # noqa: F401 - embedder is a fixture
    HANDBOOK,
    embedder,
    projects,
)


def trial(chunk_size=1000, overlap_size=200, hit_rate=0.9, mrr=0.8, recall=0.9, chunks=20):
    return Trial(chunk_size=chunk_size, overlap_size=overlap_size, hit_rate=hit_rate,
                 recall=recall, mrr=mrr, above_min_score=hit_rate, rejected=0.0, chunks=chunks,
                 indexing_seconds=1.0, suggested_min_score=None)


def test_the_grid_pairs_each_size_with_the_smaller_overlaps():
    assert grid([500, 100, 500], [0, 100, 200]) == [(100, 0), (500, 0), (500, 100), (500, 200)]
    assert grid([100], [100, 200]) == []


def test_trials_rank_by_hit_rate_then_mrr_then_recall_then_fewer_chunks():
    best = trial(chunk_size=500, hit_rate=1.0, mrr=0.5)
    by_mrr = trial(chunk_size=750, mrr=0.9)
    by_recall = trial(chunk_size=1000, recall=1.0)
    cheaper = trial(chunk_size=1500, chunks=10)
    last = trial(chunk_size=2000, chunks=30)
    unknown = trial(chunk_size=300, hit_rate=None, mrr=None, recall=None)

    assert rank([unknown, last, cheaper, by_recall, by_mrr, best]) == [
        best, by_mrr, by_recall, cheaper, last, unknown]


def test_tunes_the_handbook_and_writes_every_trial(db, embedder, tmp_path, capsys):  # noqa: F811
    output = tmp_path / "tune.json"

    assert cli.main(["tune", HANDBOOK, "--chunk-sizes", f"400,{DEFAULT_CHUNK_SIZE}",
                     "--overlaps", f"0,{DEFAULT_OVERLAP_SIZE}", "--output", str(output)]) == (
        cli.PASSED)

    out = capsys.readouterr().out
    assert "[4/4] chunks of 1000 with 200 overlap" in out
    assert "(the default)" in out and "Best: chunks of" in out
    result = json.loads(output.read_text())
    assert [(t["chunk_size"], t["overlap_size"]) for t in result["trials"]] == [
        (t.chunk_size, t.overlap_size) for t in rank([Trial(**t) for t in result["trials"]])]
    assert {(t["chunk_size"], t["overlap_size"]) for t in result["trials"]} == {
        (400, 0), (400, 200), (1000, 0), (1000, 200)}
    assert result["best"] == result["trials"][0]
    assert result["parameters"]["dataset"] == "handbook/v1"
    assert "chunk_size" not in result["parameters"]
    # Smaller chunks, more of them.
    by_size = {(t["chunk_size"], t["overlap_size"]): t["chunks"] for t in result["trials"]}
    assert by_size[(400, 0)] > by_size[(1000, 0)]
    assert projects(db) == 0  # Every run's temporary project is gone.


@pytest.mark.parametrize("option, value", [("--chunk-sizes", "0,500"), ("--overlaps", "a,b"),
                                           ("--chunk-sizes", ",")])
def test_sizes_must_be_whole_numbers(option, value, capsys):
    with pytest.raises(SystemExit):
        cli.main(["tune", HANDBOOK, option, value])
    assert option in capsys.readouterr().err


def test_needs_an_overlap_smaller_than_a_chunk_size(capsys):
    assert cli.main(["tune", HANDBOOK, "--chunk-sizes", "100", "--overlaps", "100"]) == (
        cli.FAILED)
    assert "nothing to try" in capsys.readouterr().err
