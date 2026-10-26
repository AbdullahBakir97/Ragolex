"""The interface services use to turn text into vectors.

Implementations live in ragolex.embeddings; tests use a deterministic fake.
"""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):

    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the same order, each ``dimensions`` long."""
        ...
