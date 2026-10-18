"""Rate limits and quotas per tenant."""

import time

import pytest

from mini_rag import cli
from mini_rag.core.config import get_settings

from .test_ask_api import upload_process_and_index


@pytest.fixture
def setting(monkeypatch):
    def set_(name, value):
        monkeypatch.setenv(name, str(value))
        get_settings.cache_clear()
    return set_


def upload(client, content, name="notes.txt", project="demo"):
    return client.post(f"/api/v1/data/upload/{project}",
                       files={"file": (name, content, "text/plain")})


def test_no_limits_by_default(client):
    response = client.get("/api/v1/projects")

    assert response.status_code == 200
    assert "X-RateLimit-Limit" not in response.headers


def test_requests_over_the_rate_limit_are_refused(client, setting):
    setting("RATE_LIMIT_PER_MINUTE", 3)
    # Keep the test inside one minute of the clock.
    if time.time() % 60 > 55:
        time.sleep(6)

    responses = [client.get("/api/v1/projects") for _ in range(4)]

    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert [r.headers["X-RateLimit-Remaining"] for r in responses] == ["2", "1", "0", "0"]
    assert responses[0].headers["X-RateLimit-Limit"] == "3"
    refused = responses[3]
    assert refused.json() == {"signal": "rate_limited"}
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert int(refused.headers["X-RateLimit-Reset"]) > time.time()
    # Health checks are never limited.
    assert client.get("/api/v1/health").status_code == 200


def test_a_tenant_can_be_given_its_own_rate_limit(client, db, setting, capsys):
    setting("RATE_LIMIT_PER_MINUTE", 1)
    client.get("/api/v1/projects")  # Creates the default tenant.

    assert cli.main(["tenants", "limits", "default", "--requests-per-minute", "0"]) == 0
    assert "requests/minute unlimited" in capsys.readouterr().out
    assert all(client.get("/api/v1/projects").status_code == 200 for _ in range(3))

    assert cli.main(["tenants", "limits", "default", "--requests-per-minute", "default"]) == 0
    assert "requests/minute default" in capsys.readouterr().out
    assert client.get("/api/v1/projects").status_code == 429


def test_answers_stop_at_the_monthly_quota(client, embedder, llm, setting):
    setting("ANSWERS_PER_MONTH", 1)
    upload_process_and_index(client)
    ask = {"question": "Where is the embedding vector stored?", "min_score": 0.2}

    first = client.post("/api/v1/ask/demo", json=ask)
    second = client.post("/api/v1/ask/demo", json=ask)
    streamed = client.post("/api/v1/ask/demo/stream", json=ask)

    assert first.status_code == 200
    assert (second.status_code, second.json()) == (429, {"signal": "answer_quota_exceeded"})
    assert streamed.status_code == 429
    assert len(llm.calls) == 1
    # Search still works: only answers count.
    assert client.post("/api/v1/search/demo", json={"query": "embedding"}).status_code == 200


def test_uploads_stop_at_the_storage_limit(client, setting, files_dir):
    setting("STORAGE_MB_PER_TENANT", 1)
    big = b"a" * 600_000

    first = upload(client, big, "a.txt")
    again = upload(client, big, "copy of a.txt")
    second = upload(client, b"b" * 600_000, "b.txt")

    assert first.status_code == 200
    assert again.json()["signal"] == "file_already_uploaded"  # Costs nothing more.
    assert (second.status_code, second.json()) == (413, {"signal": "storage_quota_exceeded"})
    assert [path.name for path in (files_dir / "demo").iterdir()] == [first.json()["file_id"]]


def test_usage_shows_the_month_and_the_limits(client, embedder, llm, setting):
    setting("ANSWERS_PER_MONTH", 100)
    setting("STORAGE_MB_PER_TENANT", 5)
    upload_process_and_index(client)
    client.post("/api/v1/ask/demo", json={"question": "Where is the embedding vector stored?",
                                          "min_score": 0.2})

    usage = client.get("/api/v1/usage").json()

    assert usage["tenant"] == "default"
    assert usage["answers"] == {"used": 1, "limit": 100}
    assert usage["storage_bytes"]["limit"] == 5 * 1024 * 1024
    assert usage["storage_bytes"]["used"] > 0
    assert usage["requests_per_minute"] is None
    assert (usage["input_tokens"], usage["output_tokens"]) == (1200, 40)
    assert usage["period_start"].endswith(("+00:00", "Z")) and "-01T00:00:00" in usage["period_start"]


def test_the_cli_shows_and_checks_limits(db, capsys):
    assert cli.main(["tenants", "limits", "acme", "--answers-per-month", "10"]) == 1
    cli.main(["tenants", "create", "acme"])
    capsys.readouterr()

    assert cli.main(["tenants", "limits", "acme", "--answers-per-month", "10",
                     "--storage-mb", "0"]) == 0
    assert capsys.readouterr().out.strip() == (
        "requests/minute default, answers/month 10, storage MB unlimited, budget default")
    cli.main(["tenants", "list"])
    assert "answers/month 10" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["tenants", "limits", "acme", "--storage-mb", "-1"])
