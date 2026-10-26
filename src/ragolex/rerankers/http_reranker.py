from collections.abc import Sequence
from typing import Any

import httpx2

from ragolex.core.errors import RerankFailed


class HTTPReranker:
    """Reranks with a server that has the common ``POST /rerank`` API.

    Cohere, Jina, vLLM, Infinity and LiteLLM speak it: the request has the
    model, the query and the documents, and the reply lists a relevance
    score per document index. Anything that fails, or a reply of another
    shape, raises RerankFailed.
    """

    def __init__(self, *, base_url: str, model: str, api_key: str = "",
                 timeout_seconds: float = 30.0, http_client: httpx2.AsyncClient | None = None):
        self.model = model
        self._url = base_url.rstrip("/") + "/rerank"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)
        self._headers = headers

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        try:
            response = await self._client.post(self._url, headers=self._headers, json={
                "model": self.model, "query": query, "documents": list(texts),
                "top_n": len(texts)})
            response.raise_for_status()
            body = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise RerankFailed(f"Rerank request to {self.model} failed") from exc
        return _scores(body, len(texts), self.model)

    async def aclose(self) -> None:
        await self._client.aclose()


def _scores(body: Any, count: int, model: str) -> list[float]:
    """Scores in document order from ``{"results": [...]}`` or a bare list of results."""
    results = body.get("results") if isinstance(body, dict) else body
    if not isinstance(results, list):
        raise RerankFailed(f"{model} sent an unexpected reply")
    scores: list[float | None] = [None] * count
    for result in results:
        index = result.get("index") if isinstance(result, dict) else None
        score = (result.get("relevance_score", result.get("score"))
                 if isinstance(result, dict) else None)
        if not isinstance(index, int) or not 0 <= index < count or not isinstance(score, int | float):
            raise RerankFailed(f"{model} sent an unexpected reply")
        scores[index] = float(score)
    if any(score is None for score in scores):
        raise RerankFailed(f"{model} did not score every document")
    return scores  # type: ignore[return-value]
