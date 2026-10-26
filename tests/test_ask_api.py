import json

import pytest

from ragolex.api.dependencies import get_llm
from ragolex.core.config import get_settings

from .fakes import FakeLLM

# One chunk per paragraph at chunk_size 60.
GUIDE = "\n\n".join([
    "Upload a file first, as text or PDF.",
    "Processing splits each file into chunks.",
    "Indexing stores an embedding vector per chunk.",
    "Search compares the question with the chunks.",
])


# The model was not called, so the answer used no tokens and cost nothing.
NOT_CALLED_USAGE = {"usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
# A question asked on its own, outside a conversation and without research mode.
NO_CONVERSATION = {"conversation_id": None, "search_question": None, "message_id": None,
                   "research": None}


def upload_process_and_index(client, project="demo", name="guide.txt", text=GUIDE,
                             content_type="text/plain"):
    response = client.post(f"/api/v1/data/upload/{project}",
                           files={"file": (name, text, content_type)})
    file_id = response.json()["file_id"]
    response = client.post(f"/api/v1/data/process/{project}",
                           json={"file_id": file_id, "chunk_size": 60, "overlap_size": 0})
    assert response.status_code == 200
    assert client.post(f"/api/v1/index/{project}").status_code == 200
    return file_id


def ask(client, project="demo", **body):
    return client.post(f"/api/v1/ask/{project}", json=body)


def test_answers_with_citations(client, embedder, llm):
    file_id = upload_process_and_index(client)

    response = ask(client, question="Where is the embedding vector stored?", min_score=0.2)

    assert response.status_code == 200
    body = response.json()
    score = body["citations"][0].pop("score")
    assert body == {
        "signal": "answer_success",
        "answer": "Each chunk gets an embedding vector [1].",
        "citations": [{"number": 1, "file_id": file_id, "chunk_index": 2, "page": None,
                       "section": None, "text": "Indexing stores an embedding vector per chunk."}],
        "prompt_version": "answer-v1",
        # FakeLLM's usage; no prices are configured, so the cost is unknown.
        "usage": {"input_tokens": 1200, "output_tokens": 40, "cost_usd": None},
        **NO_CONVERSATION,
    }
    assert 0.2 <= score <= 1
    # The model saw the question and only the matching chunk, as data.
    [[system, user]] = llm.calls
    assert "only as data" in system.content
    assert "Indexing stores an embedding vector per chunk." in user.content
    assert "Upload a file first" not in user.content
    assert "<question>\nWhere is the embedding vector stored?\n</question>" in user.content


def test_pdf_citations_carry_the_page(client, embedder, llm, make_pdf):
    pdf = make_pdf(["Nothing to see here.", "Each chunk gets an embedding vector."])
    upload_process_and_index(client, name="guide.pdf", text=pdf, content_type="application/pdf")

    citations = ask(client, question="embedding vector", min_score=0.2).json()["citations"]

    assert [citation["page"] for citation in citations] == [2]


def test_markdown_citations_carry_the_section(client, embedder, llm):
    text = b"# Guide\n\n## Indexing\n\nEach chunk gets an embedding vector."
    upload_process_and_index(client, name="guide.md", text=text, content_type="text/markdown")

    conversation = client.post("/api/v1/projects/demo/conversations", json={}).json()["id"]
    body = ask(client, question="embedding vector", min_score=0.2,
               conversation_id=conversation).json()
    stored = client.get(f"/api/v1/projects/demo/conversations/{conversation}").json()

    assert [c["section"] for c in body["citations"]] == ["Guide > Indexing"]
    assert [c["section"] for c in stored["messages"][1]["citations"]] == ["Guide > Indexing"]


def test_no_matching_chunk_means_no_answer(client, embedder, llm):
    upload_process_and_index(client)

    response = ask(client, question="Where is Paris?")

    assert response.status_code == 200
    assert response.json() == {"signal": "no_answer", "answer": None, "citations": [],
                               "prompt_version": "answer-v1", **NOT_CALLED_USAGE,
                               **NO_CONVERSATION}
    assert llm.calls == []


def test_model_finding_no_answer_means_no_answer(client, embedder, llm):
    upload_process_and_index(client)
    llm.reply = "NO_ANSWER"

    response = ask(client, question="Why is the embedding vector stored?", min_score=0.2)

    assert response.json()["signal"] == "no_answer"
    assert len(llm.calls) == 1


def test_unindexed_project_has_no_answer(client, embedder, llm):
    client.post("/api/v1/data/upload/demo", files={"file": ("a.txt", GUIDE, "text/plain")})

    assert ask(client, question="embedding vector").json()["signal"] == "no_answer"


def test_unknown_project(client, embedder, llm):
    response = ask(client, project="missing", question="anything")

    assert (response.status_code, response.json()) == (404, {"signal": "project_not_found"})


@pytest.mark.parametrize("body", [
    {"question": ""},
    {"question": "   "},
    {"question": "x" * 2001},
    {"question": "ok", "top_k": 0},
    {"question": "ok", "top_k": 21},
    {"question": "ok", "min_score": -1.5},
    {"query": "ok"},
])
def test_validates_the_request(client, embedder, llm, body):
    assert ask(client, **body).status_code == 422


def test_reports_model_failures(client, embedder):
    client.app.dependency_overrides[get_llm] = lambda: FakeLLM(fail=True)
    upload_process_and_index(client)

    response = ask(client, question="embedding vector", min_score=0.2)

    assert (response.status_code, response.json()) == (502, {"signal": "llm_failed"})


def test_without_llm_configuration(client, embedder):
    client.app.state.llm = None

    response = ask(client, question="anything")

    assert (response.status_code, response.json()) == (503, {"signal": "llm_not_configured"})


def test_without_embedding_configuration(client, llm):
    client.app.state.embedder = None

    response = ask(client, question="anything")

    assert (response.status_code, response.json()) == (503, {"signal": "embedding_not_configured"})


def stream_events(client, project="demo", **body):
    """POST to the streaming endpoint; the status and the (event, data) pairs it sent."""
    with client.stream("POST", f"/api/v1/ask/{project}/stream", json=body) as response:
        if response.headers["content-type"].startswith("application/json"):
            response.read()
            return response.status_code, response.json()
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return response.status_code, events


def test_stream_sends_the_answer_as_it_is_written(client, embedder, llm):
    file_id = upload_process_and_index(client)
    llm.piece_size = 6

    status, events = stream_events(client, question="Where is the embedding vector stored?",
                                   min_score=0.2)

    assert status == 200
    *deltas, (last, answer) = events
    assert {name for name, _ in deltas} == {"delta"} and len(deltas) > 1
    assert "".join(data["text"] for _, data in deltas) == "Each chunk gets an embedding vector [1]."
    assert last == "answer"
    assert answer["signal"] == "answer_success"
    assert answer["answer"] == "Each chunk gets an embedding vector [1]."
    assert [(c["number"], c["file_id"], c["chunk_index"]) for c in answer["citations"]] == [
        (1, file_id, 2)]


def test_stream_no_answer_sends_only_the_final_event(client, embedder, llm):
    upload_process_and_index(client)

    status, events = stream_events(client, question="Where is Paris?")

    assert (status, events) == (200, [("answer", {"signal": "no_answer", "answer": None,
                                                  "citations": [],
                                                  "prompt_version": "answer-v1",
                                                  **NOT_CALLED_USAGE, **NO_CONVERSATION})])
    assert llm.calls == []


def test_stream_reports_a_model_failure_as_an_event(client, embedder):
    client.app.dependency_overrides[get_llm] = lambda: FakeLLM("Each chunk [1].", fail_after=1)
    upload_process_and_index(client)

    status, events = stream_events(client, question="embedding vector", min_score=0.2)

    assert status == 200
    assert events == [("delta", {"text": "Each"}), ("error", {"signal": "llm_failed"})]


@pytest.mark.parametrize(("project", "status", "signal"), [
    ("missing", 404, "project_not_found"),
])
def test_stream_errors_before_streaming_are_plain_responses(client, embedder, llm, project,
                                                            status, signal):
    assert stream_events(client, project=project, question="anything") == (
        status, {"signal": signal})


def test_stream_without_llm_configuration(client, embedder):
    client.app.state.llm = None

    assert stream_events(client, question="anything") == (503, {"signal": "llm_not_configured"})


def test_stream_validates_the_request(client, embedder, llm):
    assert client.post("/api/v1/ask/demo/stream", json={"question": " "}).status_code == 422


def test_answers_report_their_cost_with_prices_set(client, embedder, llm, monkeypatch):
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MILLION", "0.4")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_MILLION", "1.6")
    get_settings.cache_clear()
    upload_process_and_index(client)

    usage = ask(client, question="embedding vector", min_score=0.2).json()["usage"]

    # 1200 prompt tokens at $0.40 and 40 reply tokens at $1.60 per million.
    assert usage == {"input_tokens": 1200, "output_tokens": 40,
                     "cost_usd": pytest.approx(0.000544)}


def test_project_usage_adds_up_its_answers(client, embedder, llm, query):
    upload_process_and_index(client)
    ask(client, question="embedding vector", min_score=0.2)
    stream_events(client, question="embedding vector", min_score=0.2)
    ask(client, question="Where is Paris?")  # no source: the model is not called

    usage = client.get("/api/v1/projects/demo/usage").json()

    assert usage == {"answers": 3, "answered": 2, "input_tokens": 2400, "output_tokens": 80,
                     "cost_usd": 0.0, "unpriced_answers": 2}
    # The streamed answer was saved too, after its last event.
    assert query("SELECT streamed, input_tokens FROM answers ORDER BY id") == [
        (False, 1200), (True, 1200), (False, 0)]


def test_project_usage_of_unknown_project(client):
    response = client.get("/api/v1/projects/missing/usage")

    assert (response.status_code, response.json()) == (404, {"signal": "project_not_found"})


def test_failed_answers_are_not_recorded(client, embedder, query):
    client.app.dependency_overrides[get_llm] = lambda: FakeLLM(fail=True)
    upload_process_and_index(client)

    assert ask(client, question="embedding vector", min_score=0.2).status_code == 502
    assert query("SELECT count(*) FROM answers") == [(0,)]


def test_answers_only_from_the_filtered_files(client, embedder, llm):
    upload_process_and_index(client)
    other = upload_process_and_index(client, name="other.txt",
                                     text="Embedding vectors are stored elsewhere entirely.")

    answer = ask(client, question="Where is the embedding vector stored?",
                 filters={"file_ids": [other]}).json()
    unknown = ask(client, question="Where is the embedding vector stored?",
                  filters={"file_ids": ["nope_missing.txt"]})

    assert {citation["file_id"] for citation in answer["citations"]} <= {other}
    assert "other.txt" in llm.calls[-1][-1].content
    assert "guide.txt" not in llm.calls[-1][-1].content
    assert (unknown.status_code, unknown.json()) == (404, {"signal": "file_not_found"})
