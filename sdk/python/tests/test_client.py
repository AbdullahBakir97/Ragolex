import asyncio
import json

import httpx
import pytest
from mini_rag_client import (
    UNSET,
    AnswerDelta,
    AnswerDone,
    AsyncMiniRag,
    MiniRag,
    MiniRagError,
    models,
)

ANSWER = {"signal": "answer_success", "answer": "25 days [1].", "citations": [],
          "prompt_version": "answer-v1",
          "usage": {"input_tokens": 120, "output_tokens": 8, "cost_usd": None}}
JOB = {"id": "j1", "file_id": "a_x.txt", "status": "queued", "stage": None, "progress": 0,
       "chunks_count": None, "attempts": 0, "max_attempts": 3, "chunk_size": 1000,
       "overlap_size": 200, "error": None, "created_at": "2026-10-18T10:00:00Z",
       "started_at": None, "finished_at": None}


def sse(*events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


class Server:
    """Answers requests from a list of responses, keeping the requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        response = self.responses.pop(0)
        return response(request) if callable(response) else response

    def client(self, api_key="mrag_test"):
        return MiniRag("https://rag.example.com/", api_key, transport=httpx.MockTransport(self))

    def async_client(self):
        return AsyncMiniRag("https://rag.example.com", "mrag_test",
                            transport=httpx.MockTransport(self))


def body(request):
    return json.loads(request.content)


def test_operations_send_their_parameters_and_return_models():
    server = Server(httpx.Response(200, json={"total": 1, "offset": 0, "limit": 5, "items": [
        {"file_id": "a_x.txt", "original_name": "x.txt", "content_type": "text/plain",
         "size_bytes": 3, "created_at": "2026-10-18T10:00:00Z", "tags": ["hr"]}]}))

    with server.client() as rag:
        files = rag.list_files("hand book", limit=5, tag="hr")

    assert isinstance(files, models.FileListResponse)
    assert files.items[0].tags == ["hr"]
    assert files.items[0].created_at.year == 2026
    request = server.requests[0]
    assert request.url.raw_path.split(b"?")[0] == b"/api/v1/projects/hand%20book/files"
    assert dict(request.url.params) == {"limit": "5", "tag": "hr"}
    assert request.headers["Authorization"] == "Bearer mrag_test"


def test_bodies_hold_only_the_fields_given_and_none_is_null():
    server = Server(httpx.Response(200, json={"signal": "search_success", "results": []}),
                    httpx.Response(200, json={"id": "w1", "project": "docs", "name": "Help",
                                              "welcome": None, "accent": "#2563eb",
                                              "allowed_origins": ["*"], "tags": [],
                                              "created_at": "2026-10-18T10:00:00Z"}))

    with server.client() as rag:
        rag.search_project("docs", query="leave", filters={"tags": ["HR"]})
        rag.update_widget("docs", "w1", welcome=None, tags=UNSET)

    assert body(server.requests[0]) == {"query": "leave", "filters": {"tags": ["HR"]}}
    assert body(server.requests[1]) == {"welcome": None}


def test_requests_are_checked_before_they_are_sent():
    server = Server()

    with server.client() as rag, pytest.raises(ValueError):
        rag.search_project("docs", query="leave", filters={"page_from": "first"})

    assert server.requests == []


def test_no_content_and_keys_are_optional():
    server = Server(httpx.Response(204))

    with server.client(api_key=None) as rag:
        assert rag.delete_file("docs", "a_x.txt") is None

    assert "Authorization" not in server.requests[0].headers
    assert server.requests[0].method == "DELETE"


def test_files_come_back_as_bytes():
    zip_bytes = b"PK\x03\x04 an archive"
    server = Server(httpx.Response(200, content=zip_bytes,
                                   headers={"Content-Type": "application/zip"}))

    with server.client() as rag:
        assert rag.export_tenant() == zip_bytes

    assert server.requests[0].url.path == "/api/v1/export"


def test_errors_carry_the_signal_and_retry_after():
    server = Server(httpx.Response(429, json={"signal": "rate_limited"}, headers={"Retry-After": "12"}),
                    httpx.Response(422, json={"detail": [{"msg": "bad"}]}),
                    httpx.Response(500, text="oops"))

    with server.client() as rag:
        with pytest.raises(MiniRagError) as limited:
            rag.list_projects()
        with pytest.raises(MiniRagError) as invalid:
            rag.list_projects()
        with pytest.raises(MiniRagError) as broken:
            rag.list_projects()

    assert (limited.value.status, limited.value.signal, limited.value.retry_after) == (429, "rate_limited", 12)
    assert invalid.value.signal == "validation_error"
    assert (broken.value.status, broken.value.signal) == (500, "http_error")


def test_a_server_it_cannot_reach():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with MiniRag("http://nowhere", transport=httpx.MockTransport(refuse)) as rag:
        with pytest.raises(MiniRagError) as error:
            rag.health()

    assert (error.value.status, error.value.signal) == (0, "network_error")


def test_newer_servers_still_read():
    server = Server(httpx.Response(200, json={"signal": "a_new_signal", "file_id": "a_x.txt",
                                              "added_later": True}))

    with server.client() as rag:
        upload = rag.upload("docs", b"Cats purr.", filename="cats.txt")

    assert upload.signal == "a_new_signal"
    assert upload.model_extra == {"added_later": True}


def test_uploads_send_the_file_and_its_tags(tmp_path):
    path = tmp_path / "leave.txt"
    path.write_text("25 days.")
    server = Server(httpx.Response(200, json={"signal": "file_uploaded_successfully", "file_id": "a_leave.txt"}))

    with server.client() as rag:
        upload = rag.upload("docs", path, tags=["hr", "v2"])

    assert upload.file_id == "a_leave.txt"
    request = server.requests[0]
    assert request.url.path == "/api/v1/data/upload/docs"
    assert b'filename="leave.txt"' in request.content and b"25 days." in request.content
    assert b'name="tags"\r\n\r\nhr,v2' in request.content


def test_add_document_uploads_processes_and_waits():
    server = Server(httpx.Response(200, json={"signal": "file_uploaded_successfully", "file_id": "a_x.txt"}),
                    httpx.Response(202, json=JOB),
                    httpx.Response(200, json={**JOB, "status": "running"}),
                    httpx.Response(200, json={**JOB, "status": "succeeded", "chunks_count": 2}))

    with server.client() as rag:
        upload = rag.add_document("docs", b"x", filename="x.txt", chunk_size=500, interval=0)

    assert upload.file_id == "a_x.txt"
    assert body(server.requests[1]) == {"file_id": "a_x.txt", "chunk_size": 500}
    assert [r.url.path for r in server.requests[2:]] == ["/api/v1/projects/docs/jobs/j1"] * 2


def test_a_failed_job_raises_and_duplicates_are_not_processed():
    server = Server(httpx.Response(200, json={**JOB, "status": "failed", "error": "file_has_no_text"}),
                    httpx.Response(200, json={"signal": "file_already_uploaded", "file_id": "a_x.txt"}))

    with server.client() as rag:
        with pytest.raises(MiniRagError) as failed:
            rag.wait_for_job("docs", "j1")
        rag.add_document("docs", b"x", filename="x.txt")

    assert failed.value.signal == "file_has_no_text"
    assert len(server.requests) == 2


def test_answers_stream_as_they_are_written():
    server = Server(httpx.Response(200, text=sse(("delta", {"text": "25 "}), ("delta", {"text": "days [1]."}),
                                                 ("answer", ANSWER)),
                                   headers={"Content-Type": "text/event-stream"}))

    with server.client() as rag:
        events = list(rag.ask_stream("docs", "How much leave?", top_k=4))

    assert events[:2] == [AnswerDelta("25 "), AnswerDelta("days [1].")]
    assert isinstance(events[2], AnswerDone) and events[2].answer.answer == "25 days [1]."
    assert body(server.requests[0]) == {"question": "How much leave?", "top_k": 4}
    assert server.requests[0].headers["Accept"] == "text/event-stream"


def test_a_stream_raises_its_error_and_an_early_end():
    failing = Server(httpx.Response(200, text=sse(("delta", {"text": "2"}), ("error", {"signal": "llm_failed"}))))
    cut = Server(httpx.Response(200, text=sse(("delta", {"text": "2"}))))
    refused = Server(httpx.Response(503, json={"signal": "llm_not_configured"}))

    for server, signal in ((failing, "llm_failed"), (cut, "llm_failed"), (refused, "llm_not_configured")):
        with server.client() as rag, pytest.raises(MiniRagError) as error:
            list(rag.ask_stream("docs", "q"))
        assert error.value.signal == signal


def test_the_async_client_does_the_same():
    server = Server(httpx.Response(200, json=ANSWER),
                    httpx.Response(200, text=sse(("delta", {"text": "25"}), ("answer", ANSWER))),
                    httpx.Response(200, json={"signal": "file_uploaded_successfully", "file_id": "a_x.txt"}),
                    httpx.Response(202, json=JOB),
                    httpx.Response(200, json={**JOB, "status": "succeeded"}))

    async def run():
        async with server.async_client() as rag:
            answer = await rag.ask_project("docs", question="How much leave?")
            events = [event async for event in rag.ask_stream("docs", "How much leave?")]
            await rag.add_document("docs", b"x", filename="x.txt")
            return answer, events

    answer, events = asyncio.run(run())

    assert answer.answer == "25 days [1]."
    assert events[0] == AnswerDelta("25") and isinstance(events[1], AnswerDone)
    assert len(server.requests) == 5
