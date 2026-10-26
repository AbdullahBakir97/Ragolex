"""Study mode: a summary, flashcards or a quiz from a document, each item linked to its source."""

import json

import pytest

from ragolex.api.dependencies import get_llm
from ragolex.core.config import get_settings
from ragolex.domain.models import Chunk
from ragolex.services.study_service import _spread

from .fakes import FakeLLM
from .test_ask_api import GUIDE


def items(*entries):
    return json.dumps({"items": list(entries)})


@pytest.fixture
def model(client):
    def use(reply, **options):
        fake = FakeLLM(reply, **options)
        client.app.dependency_overrides[get_llm] = lambda: fake
        return fake
    return use


def processed(client, project="demo", name="guide.txt", text=GUIDE):
    """Upload and process a file into one chunk per paragraph; returns its file_id."""
    file_id = client.post(f"/api/v1/data/upload/{project}",
                          files={"file": (name, text, "text/plain")}).json()["file_id"]
    response = client.post(f"/api/v1/data/process/{project}",
                           json={"file_id": file_id, "chunk_size": 60, "overlap_size": 0})
    assert response.status_code == 200
    return file_id


def study(client, file_id, kind, project="demo", **body):
    return client.post(f"/api/v1/study/{project}", json={"file_id": file_id, "kind": kind, **body})


def test_flashcards_cite_the_passages_they_come_from(client, model):
    file_id = processed(client)
    llm = model(items(
        {"front": "What does processing do?", "back": "Splits files into chunks.",
         "sources": [2]},
        {"front": "What does indexing store?", "back": "An embedding vector per chunk.",
         "sources": [3, 2]},
        {"front": "Invented?", "back": "Yes.", "sources": [9]}))

    response = study(client, file_id, "flashcards", count=5)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "flashcards"
    assert (body["file_id"], body["original_name"]) == (file_id, "guide.txt")
    assert body["items"] == [
        {"front": "What does processing do?", "back": "Splits files into chunks.",
         "sources": [2]},
        {"front": "What does indexing store?", "back": "An embedding vector per chunk.",
         "sources": [3, 2]}]
    assert body["sources"] == [
        {"number": 2, "chunk_index": 1, "page": None, "section": None,
         "text": "Processing splits each file into chunks."},
        {"number": 3, "chunk_index": 2, "page": None, "section": None,
         "text": "Indexing stores an embedding vector per chunk."}]
    assert body["prompt_version"] == "study-flashcards-v1"
    assert (body["passages"], body["chunks"]) == (4, 4)
    assert body["usage"]["input_tokens"] == 1200
    # The whole document went to the model, as data.
    [[system, user]] = llm.calls
    assert "flashcards" in system.content
    assert user.content.count("<passage id=") == 4
    assert user.content.endswith("Write at most 5 flashcards.")


def test_a_summary_lists_key_points(client, model):
    file_id = processed(client)
    model(items({"text": "Files are uploaded, processed into chunks and indexed.",
                 "sources": [1, 2, 3]}))

    body = study(client, file_id, "summary").json()

    assert body["items"] == [{"text": "Files are uploaded, processed into chunks and indexed.",
                              "sources": [1, 2, 3]}]
    assert [source["number"] for source in body["sources"]] == [1, 2, 3]


def test_a_quiz_has_choices_the_right_one_and_why(client, model):
    file_id = processed(client)
    question = {"question": "What is stored per chunk?",
                "choices": ["A thumbnail", "An embedding vector", "A password", "Nothing"],
                "answer": 1, "explanation": "Indexing stores an embedding vector per chunk.",
                "sources": [3]}
    model(items(question, {**question, "choices": ["Only", "three", "choices"]}))

    body = study(client, file_id, "quiz", count=3).json()

    assert body["items"] == [question]


def test_study_material_from_a_pdf_links_to_its_pages(client, model, make_pdf):
    pdf = make_pdf(["Cats purr when content.", "Kittens purr while nursing."])
    file_id = client.post("/api/v1/data/upload/demo",
                          files={"file": ("cats.pdf", pdf, "application/pdf")}).json()["file_id"]
    client.post("/api/v1/data/process/demo", json={"file_id": file_id})
    model(items({"front": "When do kittens purr?", "back": "While nursing.", "sources": [2]}))

    body = study(client, file_id, "flashcards").json()

    assert [(source["page"], source["text"]) for source in body["sources"]] == [
        (2, "Kittens purr while nursing.")]


def test_nothing_usable_gives_no_items(client, model):
    file_id = processed(client)
    model("I'm sorry, I can't do that.")

    body = study(client, file_id, "summary").json()

    assert (body["items"], body["sources"]) == ([], [])


def test_studying_is_counted_like_an_answer(client, model, monkeypatch):
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_MILLION", "2")
    get_settings.cache_clear()
    file_id = processed(client)
    model(items({"text": "Point.", "sources": [1]}))

    body = study(client, file_id, "summary").json()

    assert body["usage"]["cost_usd"] == pytest.approx((1200 * 1 + 40 * 2) / 1e6)
    usage = client.get("/api/v1/projects/demo/usage").json()
    assert (usage["answers"], usage["answered"], usage["input_tokens"]) == (1, 1, 1200)


def test_the_answer_quota_applies(client, model, monkeypatch):
    monkeypatch.setenv("ANSWERS_PER_MONTH", "1")
    get_settings.cache_clear()
    file_id = processed(client)
    model(items({"text": "Point.", "sources": [1]}))

    assert study(client, file_id, "summary").status_code == 200
    refused = study(client, file_id, "summary")
    assert (refused.status_code, refused.json()["signal"]) == (429, "answer_quota_exceeded")


def test_a_file_must_be_processed_first(client, model):
    file_id = client.post("/api/v1/data/upload/demo",
                          files={"file": ("new.txt", b"Fresh.", "text/plain")}).json()["file_id"]
    llm = model(items())

    response = study(client, file_id, "quiz")

    assert (response.status_code, response.json()["signal"]) == (409, "file_not_processed")
    assert llm.calls == []


@pytest.mark.parametrize(("project", "file_id", "signal"), [
    ("demo", "abc123_missing.txt", "file_not_found"),
    ("nowhere", "abc123_missing.txt", "project_not_found"),
])
def test_unknown_files_and_projects(client, model, project, file_id, signal):
    processed(client)
    model(items())

    response = study(client, file_id, "summary", project=project)

    assert (response.status_code, response.json()["signal"]) == (404, signal)


def test_a_failing_model_is_reported(client, model):
    file_id = processed(client)
    model("", fail=True)

    response = study(client, file_id, "flashcards")

    assert (response.status_code, response.json()["signal"]) == (502, "llm_failed")


@pytest.mark.parametrize("body", [
    {"kind": "essay"}, {"kind": "quiz", "count": 0}, {"kind": "quiz", "count": 31}, {},
])
def test_invalid_requests_are_rejected(client, body):
    file_id = processed(client)

    assert client.post("/api/v1/study/demo", json={"file_id": file_id, **body}).status_code == 422


def test_a_long_document_is_given_in_chunks_spread_over_it(client, model, monkeypatch):
    monkeypatch.setenv("STUDY_MAX_CHARACTERS", "1000")
    get_settings.cache_clear()
    # 40 paragraphs of about 55 characters: 2,200 in all.
    text = "\n\n".join(f"Paragraph {n:02d} says something worth remembering."
                       for n in range(40))
    file_id = processed(client, name="long.txt", text=text)
    llm = model(items({"text": "Point.", "sources": [21]}))

    body = study(client, file_id, "summary").json()

    # Every other chunk, about: 21 of the 40.
    assert (body["passages"], body["chunks"]) == (21, 40)
    [[_, user]] = llm.calls
    assert "Paragraph 00" in user.content and "Paragraph 39" not in user.content
    assert len(user.content) < 1000 + 40 * len('<passage id="10">\n\n</passage>\n') + 200
    # Items cite passages by number; their sources point at the chunks themselves.
    assert body["sources"][0]["chunk_index"] == 38


def chunks(*sizes):
    return [Chunk(index=index, text="x" * size) for index, size in enumerate(sizes)]


def test_spreading_keeps_everything_that_fits():
    assert len(_spread(chunks(10, 10, 10), 30)) == 3


def test_spreading_takes_chunks_evenly_in_order():
    picked = _spread(chunks(*[10] * 10), 30)

    assert [chunk.index for chunk in picked] == [0, 3, 6]


def test_spreading_takes_fewer_when_the_picked_ones_are_long():
    # Three would fit on average, but every other chunk is long: 0, 2 and 4 do not fit.
    picked = _spread(chunks(40, 1, 40, 1, 40, 1), 81)

    assert [chunk.index for chunk in picked] == [0, 3]


def test_spreading_always_keeps_one_chunk():
    assert [chunk.index for chunk in _spread(chunks(500, 500), 10)] == [0]
