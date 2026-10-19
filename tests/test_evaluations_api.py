"""Evaluation runs: recorded by `mini-rag eval`, listed for the admin dashboard."""

import pytest

from mini_rag import cli
from mini_rag.core.config import get_settings

from .test_auth import bearer, make_key
from .test_eval_command import HANDBOOK, embedder  # noqa: F401 (a fixture)

GATED = {"hit_rate", "recall", "mrr", "above_min_score", "rejected"}


def runs(client, headers=None, **params):
    response = client.get("/api/v1/evaluations", headers=headers or {}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_an_evaluation_is_recorded_for_the_dashboard(client, embedder, capsys):  # noqa: F811
    assert cli.main(["eval", HANDBOOK, "--top-k", "3"]) == cli.PASSED
    assert "Recorded for the admin dashboard of tenant default." in capsys.readouterr().out

    listed = runs(client)

    assert listed["total"] == 1
    [run] = listed["items"]
    assert (run["dataset"], run["dataset_version"], run["cases"]) == ("handbook", "v1", 53)
    assert run["parameters"]["top_k"] == 3
    assert run["parameters"]["embedding_model"] == "text-embedding-3-small"
    assert GATED <= set(run["metrics"])
    assert 0 < run["metrics"]["hit_rate"] <= 1
    assert run["answer_metrics"] is None
    assert run["version"] == get_settings().APP_VERSION


def test_runs_are_listed_newest_first_and_by_dataset(client, embedder):  # noqa: F811
    for top_k in ("1", "2", "3"):
        assert cli.main(["eval", HANDBOOK, "--top-k", top_k]) == cli.PASSED

    newest = runs(client, limit=2)
    assert newest["total"] == 3
    assert [run["parameters"]["top_k"] for run in newest["items"]] == [3, 2]
    assert runs(client, offset=2)["items"][0]["parameters"]["top_k"] == 1
    assert runs(client, dataset="handbook")["total"] == 3
    assert runs(client, dataset="other")["total"] == 0


def test_a_run_can_be_left_unrecorded(client, embedder, capsys):  # noqa: F811
    assert cli.main(["eval", HANDBOOK, "--no-record"]) == cli.PASSED

    assert "Recorded" not in capsys.readouterr().out
    assert runs(client)["total"] == 0


def test_a_run_for_an_unknown_tenant_is_not_recorded(client, embedder, capsys):  # noqa: F811
    # The evaluation itself stands.
    assert cli.main(["eval", HANDBOOK, "--tenant", "nobody"]) == cli.PASSED

    assert "there is no tenant 'nobody'" in capsys.readouterr().err
    assert runs(client)["total"] == 0


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()


def test_runs_belong_to_their_tenant_and_need_an_admin_key(client, db, auth,
                                                            embedder):  # noqa: F811
    acme, globex = make_key(db, "acme"), make_key(db, "globex")
    reader = make_key(db, "acme", scopes=("read",), name="reader")

    assert cli.main(["eval", HANDBOOK, "--tenant", "acme"]) == cli.PASSED

    assert runs(client, bearer(acme))["total"] == 1
    assert runs(client, bearer(globex))["total"] == 0
    refused = client.get("/api/v1/evaluations", headers=bearer(reader))
    assert (refused.status_code, refused.json()["signal"]) == (403, "api_key_scope_missing")


def test_the_page_size_is_bounded(client):
    assert client.get("/api/v1/evaluations", params={"limit": 101}).status_code == 422
