"""Tracing: a request's trace holds its queries and the steps of the pipeline."""

import logging
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ragolex.api.dependencies import get_embedder, get_llm
from ragolex.core import tracing
from ragolex.core.config import get_settings

from .fakes import FakeEmbedder, FakeLLM
from .test_ask_api import upload_process_and_index

otel = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session", autouse=True)
def tracer_provider():
    """One provider for the run, exporting to memory: OpenTelemetry allows setting it once."""
    provider = otel.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def traced_client(db, monkeypatch):
    monkeypatch.setenv("TRACING_ENABLED", "true")
    get_settings.cache_clear()
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        client.app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
        client.app.dependency_overrides[get_llm] = lambda: FakeLLM(
            "Each chunk gets an embedding vector [1].")
        EXPORTER.clear()
        yield client


def spans_of(trace_id):
    return {span.name: span for span in EXPORTER.get_finished_spans()
            if span.context.trace_id == trace_id}


def test_an_answer_is_traced_step_by_step(traced_client):
    upload_process_and_index(traced_client)
    EXPORTER.clear()

    response = traced_client.post("/api/v1/ask/demo", json={
        "question": "Where is the embedding vector stored?", "min_score": 0.2})

    assert response.status_code == 200
    [request] = [span for span in EXPORTER.get_finished_spans()
                 if span.name == "POST /api/v1/ask/{project_id}"]
    spans = spans_of(request.context.trace_id)
    assert {"search.embed_query", "search.query", "answer.generate"} <= set(spans)
    assert spans["search.query"].attributes["results"] >= 1
    generated = spans["answer.generate"].attributes
    assert generated["prompt_version"] == "answer-v1"
    assert generated["gen_ai.usage.input_tokens"] > 0
    # The database queries are in the same trace, each a span of its own.
    queries = [span for span in EXPORTER.get_finished_spans()
               if span.context.trace_id == request.context.trace_id
               and span.attributes.get("db.system") == "postgresql"]
    assert queries


def test_a_streamed_answer_has_its_generation_span(traced_client):
    upload_process_and_index(traced_client)
    EXPORTER.clear()

    with traced_client.stream("POST", "/api/v1/ask/demo/stream", json={
            "question": "Where is the embedding vector stored?", "min_score": 0.2}) as response:
        body = response.read().decode()

    assert "event: answer" in body
    [generated] = [span for span in EXPORTER.get_finished_spans()
                   if span.name == "answer.generate"]
    assert generated.attributes["streamed"] is True


def test_jobs_are_traced(traced_client, run_jobs):
    response = traced_client.post("/api/v1/data/upload/demo",
                                  files={"file": ("notes.txt", b"Cats purr when happy.",
                                                  "text/plain")})
    file_id = response.json()["file_id"]
    EXPORTER.clear()
    traced_client.post("/api/v1/projects/demo/jobs", json={"file_id": file_id})
    run_jobs()

    names = [span.name for span in EXPORTER.get_finished_spans()]
    assert {"job", "job.process", "job.index"} <= set(names)


def test_queries_outside_a_trace_are_not_traced(traced_client):
    # Such as a worker polling for jobs: a trace of one query, every second.
    engine = traced_client.app.state.engine

    async def query():
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    traced_client.portal.call(query)

    assert not [span for span in EXPORTER.get_finished_spans()
                if span.attributes.get("db.system") == "postgresql"]


def test_health_checks_are_not_traced(traced_client):
    traced_client.get("/api/v1/health")

    assert not [span for span in EXPORTER.get_finished_spans()
                if span.name.startswith("GET /api/v1/health")]


def test_log_lines_carry_the_trace_id(traced_client, caplog):
    with caplog.at_level(logging.INFO, logger="ragolex.access"):
        traced_client.get("/api/v1/projects")

    [request] = [span for span in EXPORTER.get_finished_spans()
                 if span.name == "GET /api/v1/projects"]
    [line] = [record for record in caplog.records if "GET /api/v1/projects" in record.getMessage()]
    assert line.trace_id == format(request.context.trace_id, "032x")


def test_outside_a_request_there_is_no_trace():
    assert tracing.current_trace_id() is None


def test_tracing_says_how_to_install_it(monkeypatch):
    # As if the tracing extra were not installed.
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", None)

    with pytest.raises(RuntimeError, match=r"pip install 'ragolex\[tracing\]'"):
        tracing.setup_tracing("ragolex", "0.1.0")
