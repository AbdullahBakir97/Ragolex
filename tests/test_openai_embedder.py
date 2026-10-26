import json

import httpx2
import pytest

from ragolex.core.config import Settings
from ragolex.core.errors import EmbeddingFailed
from ragolex.embeddings.factory import create_embedder
from ragolex.embeddings.openai_embedder import OpenAIEmbedder

pytestmark = pytest.mark.anyio


class FakeEmbeddingsServer:
    """Answers POST /embeddings like the OpenAI API and records the requests."""

    def __init__(self, dimensions=3, status_code=200, drop_last=False):
        self.dimensions = dimensions
        self.status_code = status_code
        self.drop_last = drop_last
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx2.Response(self.status_code, json={"error": {"message": "boom"}})
        texts = json.loads(request.content)["input"]
        if self.drop_last:
            texts = texts[:-1]
        # Reversed on purpose: the API does not promise any order.
        data = [{"object": "embedding", "index": i,
                 "embedding": [float(len(text)), float(i), *[0.0] * (self.dimensions - 2)]}
                for i, text in reversed(list(enumerate(texts)))]
        return httpx2.Response(200, json={
            "object": "list", "data": data, "model": "test-model",
            "usage": {"prompt_tokens": 1, "total_tokens": 1}})

    @property
    def last_body(self):
        return json.loads(self.requests[-1].content)


def make_embedder(server, **overrides):
    options = {"api_key": "sk-test", "model": "test-model", "dimensions": 3,
               "base_url": "http://embeddings.test/v1", "max_retries": 0,
               "http_client": httpx2.AsyncClient(transport=httpx2.MockTransport(server))}
    return OpenAIEmbedder(**{**options, **overrides})


async def test_embeds_texts_in_input_order():
    server = FakeEmbeddingsServer()
    embedder = make_embedder(server)

    vectors = await embedder.embed(["a", "bbb"])

    assert vectors == [[1.0, 0.0, 0.0], [3.0, 1.0, 0.0]]
    assert server.requests[0].url == "http://embeddings.test/v1/embeddings"
    assert server.requests[0].headers["authorization"] == "Bearer sk-test"
    assert server.last_body == {"model": "test-model", "input": ["a", "bbb"], "dimensions": 3,
                                "encoding_format": "float"}


async def test_no_texts_need_no_request():
    server = FakeEmbeddingsServer()

    assert await make_embedder(server).embed([]) == []
    assert server.requests == []


async def test_a_server_without_a_key_gets_a_placeholder():
    server = FakeEmbeddingsServer()

    await make_embedder(server, api_key="").embed(["a"])

    assert server.requests[0].headers["authorization"] == "Bearer not-needed"


@pytest.mark.parametrize("server", [
    FakeEmbeddingsServer(status_code=500),
    FakeEmbeddingsServer(status_code=401),
    FakeEmbeddingsServer(dimensions=4),  # wrong length
    FakeEmbeddingsServer(drop_last=True),  # one vector missing
], ids=["server-error", "bad-key", "wrong-dimensions", "missing-vector"])
async def test_failures_raise_embedding_failed(server):
    with pytest.raises(EmbeddingFailed):
        await make_embedder(server).embed(["a", "b"])


@pytest.mark.parametrize(("content_type", "body", "shown"), [
    ("text/plain", "OK", "OK"),
    ("text/html", "<html><body>Sign in</body></html>", "<html><body>Sign in"),
    ("application/json", '{"unexpected": true}', "unexpected=True"),
], ids=["plain-text", "html", "json-of-another-shape"])
async def test_a_reply_that_is_not_embeddings_raises_embedding_failed(content_type, body, shown):
    def answer(request):
        return httpx2.Response(200, headers={"content-type": content_type}, text=body)

    with pytest.raises(EmbeddingFailed, match="unexpected reply") as error:
        await make_embedder(answer).embed(["a"])
    # The start of the reply is kept, to show what the server sent instead.
    assert shown in str(error.value)


async def test_unreachable_server_raises_embedding_failed():
    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(EmbeddingFailed):
        await make_embedder(refuse).embed(["a"])


def test_factory_returns_none_without_key_or_server(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    assert create_embedder(Settings()) is None


def test_factory_uses_the_embedding_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "local-model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")

    embedder = create_embedder(Settings())

    assert (embedder.model, embedder.dimensions) == ("local-model", 768)
    assert str(embedder._client.base_url) == "http://localhost:11434/v1/"
