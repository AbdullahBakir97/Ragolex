"""The interface search uses to reorder results with a reranking model.

A reranker reads the question and each passage together, which judges
relevance better than comparing two separate embeddings, but costs a call
per search. Implementations live in ragolex.rerankers.
"""

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):

    model: str

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """A relevance score for each text, in the given order; higher is more relevant."""
        ...
