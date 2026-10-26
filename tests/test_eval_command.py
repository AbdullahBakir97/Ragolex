import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from ragolex import cli
from ragolex.core.config import get_settings
from ragolex.persistence.database import create_engine

from .fakes import FakeEmbedder, FakeLLM

HANDBOOK = str(Path(__file__).resolve().parents[1] / "evals" / "handbook" / "v1")


class ClosableEmbedder(FakeEmbedder):
    async def aclose(self) -> None:
        pass


@pytest.fixture
def embedder(db, monkeypatch):
    fake = ClosableEmbedder()
    monkeypatch.setattr(cli, "create_embedder", lambda settings: fake)
    return fake


def projects(db) -> int:
    async def count():
        engine = create_engine(db)
        try:
            async with engine.connect() as connection:
                return await connection.scalar(text("SELECT count(*) FROM projects"))
        finally:
            await engine.dispose()
    return asyncio.run(count())


def test_evaluates_the_handbook_and_writes_a_report(db, embedder, tmp_path, capsys):
    report_path = tmp_path / "report.json"

    assert cli.main(["eval", HANDBOOK, "--output", str(report_path)]) == cli.PASSED

    out = capsys.readouterr().out
    assert "Retrieval on handbook/v1: 53 questions (46 answerable), 8 documents" in out
    report = json.loads(report_path.read_text())
    assert report["parameters"] == {
        "dataset": "handbook/v1", "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536, "search_mode": "hybrid", "reranker": None, "top_k": 5, "chunk_size": 1000, "overlap_size": 200,
        "min_score": 0.3}
    assert len(report["cases"]) == 53
    assert 0 < report["metrics"]["hit_rate"] <= 1
    # The PDF's pages are read and cited like in the API.
    pdf_hits = [hit for case in report["cases"] for hit in case["results"]
                if hit["file"] == "security-policy.pdf"]
    assert pdf_hits and all(hit["page"] in (1, 2) for hit in pdf_hits)
    assert projects(db) == 0


def test_passes_against_its_own_baseline_and_fails_below_it(db, embedder, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    assert cli.main(["eval", HANDBOOK, "--save-baseline", str(baseline)]) == cli.PASSED

    assert cli.main(["eval", HANDBOOK, "--baseline", str(baseline)]) == cli.PASSED
    assert "mrr" in capsys.readouterr().out

    raised = json.loads(baseline.read_text())
    raised["metrics"]["mrr"] = min(1.0, raised["metrics"]["mrr"] + 0.1)
    baseline.write_text(json.dumps(raised))
    assert cli.main(["eval", HANDBOOK, "--baseline", str(baseline)]) == cli.REGRESSED
    assert "Retrieval got worse than the baseline." in capsys.readouterr().out


def test_a_baseline_with_other_parameters_fails_before_the_run(db, embedder, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"parameters": {"dataset": "handbook/v1", "top_k": 3},
                                    "metrics": {"mrr": 0.5}}))

    assert cli.main(["eval", HANDBOOK, "--baseline", str(baseline)]) == cli.FAILED

    assert "other parameters" in capsys.readouterr().err
    assert embedder.calls == []


def test_needs_an_embedding_model(db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_embedder", lambda settings: None)

    assert cli.main(["eval", HANDBOOK]) == cli.FAILED
    assert "No embedding model is configured" in capsys.readouterr().err


def test_reports_a_failing_embedding_model(db, monkeypatch, capsys):
    failing = ClosableEmbedder(fail_on_call=1)
    monkeypatch.setattr(cli, "create_embedder", lambda settings: failing)

    assert cli.main(["eval", HANDBOOK]) == cli.FAILED
    assert "The evaluation failed: fake failure" in capsys.readouterr().err
    assert projects(db) == 0


def test_reports_an_unreachable_database(embedder, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    get_settings.cache_clear()

    assert cli.main(["eval", HANDBOOK]) == cli.FAILED
    assert "unreachable or not migrated" in capsys.readouterr().err


def test_reports_an_invalid_dataset(tmp_path, capsys):
    assert cli.main(["eval", str(tmp_path)]) == cli.FAILED
    assert "dataset.json: cannot be read" in capsys.readouterr().err


def test_overlap_must_be_smaller_than_the_chunks(capsys):
    with pytest.raises(SystemExit):
        cli.main(["eval", HANDBOOK, "--chunk-size", "100", "--overlap-size", "100"])
    assert "--overlap-size must be smaller" in capsys.readouterr().err


class ClosableLLM(FakeLLM):
    async def aclose(self) -> None:
        pass


def test_answers_are_evaluated_with_the_judge(db, embedder, monkeypatch, tmp_path, capsys):
    writer = ClosableLLM("Production deploys happen on weekdays between 9:00 and 16:00 [1].")
    judge = ClosableLLM('{"grounded": "yes", "correct": "yes", "reason": "Fine."}')
    models = iter([writer, judge])
    monkeypatch.setattr(cli, "create_llm", lambda settings: next(models))
    report_path = tmp_path / "report.json"

    assert cli.main(["eval", HANDBOOK, "--answers", "--min-score", "-1",
                     "--output", str(report_path)]) == cli.PASSED

    out = capsys.readouterr().out
    assert "Answers by gpt-4.1-mini (answer-v1), graded by fake-llm (judge-v1)" in out
    report = json.loads(report_path.read_text())
    metrics = report["answer_metrics"]
    assert (metrics["answered"], metrics["abstained"], metrics["correct"]) == (1.0, 0.0, 1.0)
    assert report["cases"][0]["answer"]["text"].startswith("Production deploys happen")
    assert report["answer_usage"]["answers"]["input_tokens"] == 53 * 1200
    assert len(judge.calls) == 53
    assert projects(db) == 0


def test_answers_need_a_language_model(db, embedder, monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_llm", lambda settings: None)

    assert cli.main(["eval", HANDBOOK, "--answers"]) == cli.FAILED
    assert "--answers needs a language model" in capsys.readouterr().err


def test_a_judge_model_needs_answers(capsys):
    with pytest.raises(SystemExit):
        cli.main(["eval", HANDBOOK, "--judge-model", "other"])
    assert "--judge-model needs --answers" in capsys.readouterr().err


def test_the_search_mode_can_be_chosen(db, embedder, tmp_path, capsys):
    report_path = tmp_path / "report.json"

    assert cli.main(["eval", HANDBOOK, "--search-mode", "vector",
                     "--output", str(report_path)]) == cli.PASSED

    assert "vector search, top 5" in capsys.readouterr().out
    assert json.loads(report_path.read_text())["parameters"]["search_mode"] == "vector"
