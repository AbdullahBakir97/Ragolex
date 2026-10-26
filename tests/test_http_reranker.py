import json

import httpx2
import pytest

from ragolex.core.config import get_settings
from ragolex.core.errors import RerankFailed
from ragolex.rerankers.factory import create_reranker
from ragolex.rerankers.http_reranker import HTTPReranker

pytestmark = pytest.mark.anyio


def reranker(handler, api_key=""):
    requests = []

    def server(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(server))
    return HTTPReranker(base_url="http://rerank.test/v1/", model="bge-reranker", api_key=api_key,
                        http_client=client), requests


async def test_scores_documents_in_their_order():
    scored, requests = reranker(lambda request: httpx2.Response(200, json={"results": [
        {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}),
        api_key="secret")

    assert await scored.rerank("q?", ["first", "second"]) == [0.2, 0.9]
    [request] = requests
    assert str(request.url) == "http://rerank.test/v1/rerank"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.content) == {"model": "bge-reranker", "query": "q?",
                                           "documents": ["first", "second"], "top_n": 2}


async def test_reads_a_bare_list_of_scores_and_sends_no_key_without_one():
    scored, requests = reranker(lambda request: httpx2.Response(
        200, json=[{"index": 0, "score": 1}, {"index": 1, "score": 0.5}]))

    assert await scored.rerank("q?", ["a", "b"]) == [1.0, 0.5]
    assert "Authorization" not in requests[0].headers


async def test_nothing_to_rerank_makes_no_request():
    scored, requests = reranker(lambda request: httpx2.Response(500))

    assert await scored.rerank("q?", []) == []
    assert requests == []


@pytest.mark.parametrize("response", [
    httpx2.Response(500, json={"error": "down"}),
    httpx2.Response(200, text="OK"),
    httpx2.Response(200, json={"data": []}),
    httpx2.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]}),
    httpx2.Response(200, json={"results": [{"index": 7, "relevance_score": 0.5},
                                           {"index": 1, "relevance_score": 0.1}]}),
    httpx2.Response(200, json={"results": [{"index": 0, "relevance_score": "high"},
                                           {"index": 1, "relevance_score": 0.1}]}),
], ids=["error", "not-json", "other-shape", "missing-score", "bad-index", "bad-score"])
async def test_unusable_replies_fail(response):
    scored, _ = reranker(lambda request: response)

    with pytest.raises(RerankFailed):
        await scored.rerank("q?", ["a", "b"])


def test_reranking_is_off_without_a_server(monkeypatch):
    assert create_reranker(get_settings()) is None

    monkeypatch.setenv("RERANK_BASE_URL", "http://rerank.test/v1")
    monkeypatch.setenv("RERANK_MODEL", "bge-reranker")
    get_settings.cache_clear()
    assert create_reranker(get_settings()).model == "bge-reranker"
