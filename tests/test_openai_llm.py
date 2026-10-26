import json

import httpx2
import pytest

from ragolex.core.config import Settings
from ragolex.core.errors import LLMFailed
from ragolex.domain.llm import Completion, Message, TokenUsage
from ragolex.llm.factory import create_llm
from ragolex.llm.openai_llm import OpenAILLM

pytestmark = pytest.mark.anyio

MESSAGES = [Message("system", "Be brief."), Message("user", "Hello?")]


class FakeChatServer:
    """Answers POST /chat/completions like the OpenAI API and records the requests."""

    def __init__(self, content="Hi there.", status_code=200, choices=True, pieces=None,
                 report_usage=True):
        self.content = content
        self.report_usage = report_usage
        self.status_code = status_code
        self.choices = choices
        # What a streamed reply is made of; defaults to two halves of content.
        self.pieces = pieces
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx2.Response(self.status_code, json={"error": {"message": "boom"}})
        if json.loads(request.content).get("stream"):
            return self.stream_response(include_usage=self.report_usage and "stream_options"
                                        in json.loads(request.content))
        choices = [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": self.content}}]
        return httpx2.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": choices if self.choices else [],
            "usage": ({"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
                      if self.report_usage else None)})

    def stream_response(self, include_usage: bool) -> httpx2.Response:
        pieces = self.pieces
        if pieces is None:
            half = len(self.content) // 2
            pieces = [self.content[:half], self.content[half:]]
        events = [{"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 0,
                   "model": "test-model",
                   "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                  for piece in pieces]
        if include_usage:
            events.append({"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 0,
                           "model": "test-model", "choices": [],
                           "usage": {"prompt_tokens": 12, "completion_tokens": 3,
                                     "total_tokens": 15}})
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               content=body.encode())

    @property
    def last_body(self):
        return json.loads(self.requests[-1].content)


def make_llm(server, **overrides):
    options = {"api_key": "sk-test", "model": "test-model", "max_tokens": 100,
               "base_url": "http://llm.test/v1", "max_retries": 0,
               "http_client": httpx2.AsyncClient(transport=httpx2.MockTransport(server))}
    return OpenAILLM(**{**options, **overrides})


async def test_sends_the_messages_and_returns_the_reply():
    server = FakeChatServer()

    reply = await make_llm(server).complete(MESSAGES)

    assert reply == Completion(text="Hi there.",
                               usage=TokenUsage(input_tokens=12, output_tokens=3))
    assert server.requests[0].url == "http://llm.test/v1/chat/completions"
    assert server.requests[0].headers["authorization"] == "Bearer sk-test"
    assert server.last_body == {
        "model": "test-model", "max_tokens": 100,
        "messages": [{"role": "system", "content": "Be brief."},
                     {"role": "user", "content": "Hello?"}]}


async def test_usage_is_none_when_the_server_does_not_report_it():
    server = FakeChatServer(report_usage=False)

    assert await make_llm(server).complete(MESSAGES) == Completion(text="Hi there.")
    assert await collect(make_llm(server)) == ["Hi t", "here."]


async def test_temperature_is_sent_only_when_set():
    server = FakeChatServer()

    await make_llm(server, temperature=0.2).complete(MESSAGES)

    assert server.last_body["temperature"] == 0.2


async def test_openai_itself_gets_max_completion_tokens():
    server = FakeChatServer()
    llm = make_llm(server, base_url=None)
    llm._client = llm._client.with_options(base_url="http://llm.test/v1")

    await llm.complete(MESSAGES)

    assert server.last_body["max_completion_tokens"] == 100
    assert "max_tokens" not in server.last_body


async def test_a_server_without_a_key_gets_a_placeholder():
    server = FakeChatServer()

    await make_llm(server, api_key="").complete(MESSAGES)

    assert server.requests[0].headers["authorization"] == "Bearer not-needed"


@pytest.mark.parametrize("server", [
    FakeChatServer(status_code=500),
    FakeChatServer(status_code=401),
    FakeChatServer(content=None),
    FakeChatServer(content="  \n"),
    FakeChatServer(choices=False),
], ids=["server-error", "bad-key", "no-content", "blank-content", "no-choices"])
async def test_failures_raise_llm_failed(server):
    with pytest.raises(LLMFailed):
        await make_llm(server).complete(MESSAGES)


@pytest.mark.parametrize(("content_type", "body", "shown"), [
    ("text/plain", "OK", "OK"),
    ("text/html", "<html><body>Sign in</body></html>", "<html><body>Sign in"),
    ("application/json", '{"unexpected": true}', "unexpected=True"),
], ids=["plain-text", "html", "json-of-another-shape"])
async def test_a_reply_that_is_not_a_completion_raises_llm_failed(content_type, body, shown):
    def answer(request):
        return httpx2.Response(200, headers={"content-type": content_type}, text=body)

    with pytest.raises(LLMFailed, match="unexpected reply") as error:
        await make_llm(answer).complete(MESSAGES)
    assert shown in str(error.value)


async def test_a_stream_that_is_not_events_raises_llm_failed():
    def answer(request):
        return httpx2.Response(200, headers={"content-type": "text/plain"}, text="OK")

    with pytest.raises(LLMFailed):
        await collect(make_llm(answer))


async def test_unreachable_server_raises_llm_failed():
    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(LLMFailed):
        await make_llm(refuse).complete(MESSAGES)


async def collect(llm):
    return [piece async for piece in llm.stream(MESSAGES)]


async def test_streams_the_reply_in_pieces():
    server = FakeChatServer(pieces=["Hi", " there", "."])

    pieces = await collect(make_llm(server))

    assert pieces == ["Hi", " there", ".", TokenUsage(input_tokens=12, output_tokens=3)]
    assert server.last_body["stream"] is True
    assert server.last_body["stream_options"] == {"include_usage": True}
    assert server.last_body["max_tokens"] == 100


async def test_stream_usage_can_be_turned_off():
    server = FakeChatServer(pieces=["Hi"])

    pieces = await collect(make_llm(server, stream_usage=False))

    assert pieces == ["Hi"]
    assert "stream_options" not in server.last_body


@pytest.mark.parametrize("server", [
    FakeChatServer(status_code=500),
    FakeChatServer(status_code=401),
    FakeChatServer(pieces=[]),
    FakeChatServer(pieces=[" ", "\n"]),
], ids=["server-error", "bad-key", "no-pieces", "blank-pieces"])
async def test_stream_failures_raise_llm_failed(server):
    with pytest.raises(LLMFailed):
        await collect(make_llm(server))


async def test_a_stream_cut_off_midway_raises_llm_failed():
    class BrokenStream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            chunk = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                     "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            raise httpx2.ReadError("connection lost")

    def cut_off(request):
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               stream=BrokenStream())

    received = []
    with pytest.raises(LLMFailed):
        async for piece in make_llm(cut_off).stream(MESSAGES):
            received.append(piece)
    assert received == ["Hi"]


def test_factory_returns_none_without_key_or_server(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    assert create_llm(Settings()) is None


def test_factory_uses_the_llm_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "local-model")
    monkeypatch.setenv("LLM_MAX_TOKENS", "256")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.1")
    monkeypatch.setenv("LLM_STREAM_USAGE", "false")

    llm = create_llm(Settings())

    assert (llm.model, llm.max_tokens, llm.temperature, llm.stream_usage) == (
        "local-model", 256, 0.1, False)
    assert str(llm._client.base_url) == "http://localhost:11434/v1/"
