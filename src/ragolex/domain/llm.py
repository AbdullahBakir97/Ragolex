"""The interface services use to generate text with a language model.

Implementations live in ragolex.llm; tests use a scripted fake.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    """One message of a chat: instructions (system), a request (user) or a reply."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class TokenUsage:
    """Tokens the model read (the prompt) and wrote (the reply)."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class TokenPrices:
    """What a model costs, in US dollars per million tokens."""

    input_per_million: float
    output_per_million: float

    def cost(self, usage: TokenUsage) -> float:
        return (usage.input_tokens * self.input_per_million
                + usage.output_tokens * self.output_per_million) / 1_000_000


@dataclass(frozen=True)
class Completion:
    """A reply; ``usage`` is None when the provider does not report it."""

    text: str
    usage: TokenUsage | None = None


class LLM(Protocol):

    model: str

    async def complete(self, messages: Sequence[Message]) -> Completion:
        """The model's reply to the conversation in ``messages``."""
        ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str | TokenUsage]:
        """The same reply in pieces as the model writes it, then its usage if reported."""
        ...
