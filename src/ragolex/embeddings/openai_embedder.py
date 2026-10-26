from collections.abc import Sequence
from typing import Any

import httpx2
from openai import AsyncOpenAI, OpenAIError

from ragolex.core.errors import EmbeddingFailed

# Servers such as Ollama need no key, but the SDK insists on one.
PLACEHOLDER_API_KEY = "not-needed"


class OpenAIEmbedder:
    """Embeds texts with the OpenAI embeddings API or a compatible server.

    Set ``base_url`` for another server, e.g. Ollama at
    http://localhost:11434/v1. Transient errors (rate limits, timeouts,
    5xx) are retried by the SDK; anything that still fails, or a response
    of the wrong shape, raises EmbeddingFailed.
    """

    def __init__(self, *, api_key: str, model: str, dimensions: int,
                 base_url: str | None = None, timeout_seconds: float = 30.0,
                 max_retries: int = 2, http_client: httpx2.AsyncClient | None = None):
        self.model = model
        self.dimensions = dimensions
        self._client = AsyncOpenAI(api_key=api_key or PLACEHOLDER_API_KEY, base_url=base_url,
                                   timeout=timeout_seconds, max_retries=max_retries,
                                   http_client=http_client)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            # Plain floats: every OpenAI-compatible server supports them,
            # unlike the SDK's default base64.
            response = await self._client.embeddings.create(
                model=self.model, input=list(texts), dimensions=self.dimensions,
                encoding_format="float")
        except OpenAIError as exc:
            raise EmbeddingFailed(f"Embedding request to {self.model} failed") from exc

        # A server that answers with something else (an HTML page, a proxy's
        # "OK") reaches us as text, or as a response without data.
        data = getattr(response, "data", None)
        if not isinstance(data, list):
            raise EmbeddingFailed(f"{self.model} sent an unexpected reply: {_preview(response)}")
        vectors = [item.embedding for item in sorted(data, key=lambda item: item.index)]
        if len(vectors) != len(texts):
            raise EmbeddingFailed(f"{self.model} returned {len(vectors)} vectors for {len(texts)} texts")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise EmbeddingFailed(f"{self.model} returned vectors that are not {self.dimensions} long")
        return vectors

    async def aclose(self) -> None:
        await self._client.close()


def _preview(response: Any) -> str:
    """The start of a reply, for error messages."""
    text = response if isinstance(response, str) else repr(response)
    return " ".join(text.split())[:200]
