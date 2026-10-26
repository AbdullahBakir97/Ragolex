"""Prometheus metrics: HTTP traffic by route, answers, uploads, jobs, and access to /metrics."""

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from ragolex.core.config import get_settings

from .fakes import FakeEmbedder
from .test_ask_api import GUIDE, upload_process_and_index


def value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def scrape(client, headers=None):
    response = client.get("/metrics", headers=headers or {})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    return response.text


def test_requests_are_counted_by_route_template(client):
    before = value("ragolex_http_requests_total", method="GET",
                   route="/api/v1/projects/{project_id}", status="404")
    unmatched = value("ragolex_http_requests_total", method="GET", route="unmatched",
                      status="404")

    client.get("/api/v1/projects/alpha")
    client.get("/api/v1/projects/beta")
    client.get("/no/such/page")

    assert value("ragolex_http_requests_total", method="GET",
                 route="/api/v1/projects/{project_id}", status="404") == before + 2
    assert value("ragolex_http_requests_total", method="GET", route="unmatched",
                 status="404") == unmatched + 1
    assert value("ragolex_http_request_duration_seconds_count", method="GET",
                 route="/api/v1/projects/{project_id}") >= 2
    # Project names never become labels.
    assert "alpha" not in scrape(client)


def test_answers_tokens_and_uploads_are_counted(client, embedder, llm):
    answered = value("ragolex_answers_total", answered="true")
    tokens = value("ragolex_llm_tokens_total", kind="output")
    stored = value("ragolex_uploads_total", outcome="stored")
    duplicates = value("ragolex_uploads_total", outcome="duplicate")

    upload_process_and_index(client)
    client.post("/api/v1/data/upload/demo", files={"file": ("again.txt", GUIDE, "text/plain")})
    client.post("/api/v1/ask/demo", json={"question": "Where is the embedding vector stored?"})

    assert value("ragolex_answers_total", answered="true") == answered + 1
    assert value("ragolex_llm_tokens_total", kind="output") > tokens
    assert value("ragolex_uploads_total", outcome="stored") == stored + 1
    assert value("ragolex_uploads_total", outcome="duplicate") == duplicates + 1


def test_waiting_work_is_reported_from_the_database(client, run_jobs):
    file_id = client.post("/api/v1/data/upload/demo", files={
        "file": ("notes.txt", b"Cats purr when happy.", "text/plain")}).json()["file_id"]
    client.post("/api/v1/projects/demo/jobs", json={"file_id": file_id})

    assert 'ragolex_jobs_in_state{status="queued"} 1.0' in scrape(client)

    succeeded = value("ragolex_jobs_total", outcome="succeeded")
    run_jobs(FakeEmbedder())

    text = scrape(client)
    assert 'ragolex_jobs_in_state{status="queued"} 0.0' in text
    assert 'ragolex_jobs_in_state{status="succeeded"} 1.0' in text
    assert value("ragolex_jobs_total", outcome="succeeded") == succeeded + 1


@pytest.fixture
def protected(db, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "scrape-me")
    get_settings.cache_clear()
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        yield client


def test_a_metrics_token_keeps_metrics_private(protected):
    missing = protected.get("/metrics")
    wrong = protected.get("/metrics", headers={"Authorization": "Bearer guess"})

    assert (missing.status_code, missing.json()) == (401, {"signal": "api_key_required"})
    assert (wrong.status_code, wrong.json()) == (401, {"signal": "api_key_invalid"})
    assert "ragolex_http_requests_total" in scrape(
        protected, {"Authorization": "Bearer scrape-me"})


def test_metrics_are_not_in_the_api_schema(client):
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]
