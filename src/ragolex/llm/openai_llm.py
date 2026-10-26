from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx2
from openai import AsyncOpenAI, OpenAIError

from ragolex.core.errors import LLMFailed
from ragolex.domain.llm import Completion, Message, TokenUsage

# Servers such as Ollama need no key, but the SDK insists on one.
PLACEHOLDER_API_KEY = "not-needed"


class OpenAILLM:
    """Generates replies with the OpenAI chat completions API or a compatible server.

    Set ``base_url`` for another server, e.g. Ollama at
    http://localhost:11434/v1. ``temperature`` None leaves it to the model,
    which reasoning models require. ``stream_usage`` asks for token usage
    at the end of a stream; turn it off for a server that rejects
    ``stream_options``. Transient errors (rate limits, timeouts,
    5xx) are retried by the SDK before a reply starts; anything that still
    fails, or a reply without text, raises LLMFailed, also partway through
    a stream.
    """

    def __init__(self, *, api_key: str, model: str, max_tokens: int,
                 temperature: float | None = None, base_url: str | None = None,
                 stream_usage: bool = True, timeout_seconds: float = 60.0, max_retries: int = 2,
                 http_client: httpx2.AsyncClient | None = None):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.stream_usage = stream_usage
        # OpenAI's newer models accept only max_completion_tokens, while
        # compatible servers such as Ollama document only max_tokens.
        self._max_tokens_parameter = "max_tokens" if base_url else "max_completion_tokens"
        self._client = AsyncOpenAI(api_key=api_key or PLACEHOLDER_API_KEY, base_url=base_url,
                                   timeout=timeout_seconds, max_retries=max_retries,
                                   http_client=http_client)

    async def complete(self, messages: Sequence[Message]) -> Completion:
        try:
            response = await self._client.chat.completions.create(**self._request(messages))
        except OpenAIError as exc:
            raise LLMFailed(f"Chat request to {self.model} failed") from exc

        # A server that answers with something else (an HTML page, a proxy's
        # "OK") reaches us as text, or as a response without choices.
        if not isinstance(getattr(response, "choices", None), list):
            raise LLMFailed(f"{self.model} sent an unexpected reply: {_preview(response)}")
        if not response.choices or not (response.choices[0].message.content or "").strip():
            raise LLMFailed(f"{self.model} returned no text")
        return Completion(text=response.choices[0].message.content,
                          usage=_usage(response.usage))

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str | TokenUsage]:
        request = self._request(messages)
        if self.stream_usage:
            # Adds a last chunk with the usage and no choices.
            request["stream_options"] = {"include_usage": True}
        received = ""
        usage = None
        try:
            chunks = await self._client.chat.completions.create(**request, stream=True)
            async for chunk in chunks:
                if chunk.choices and chunk.choices[0].delta.content:
                    received += chunk.choices[0].delta.content
                    yield chunk.choices[0].delta.content
                usage = _usage(chunk.usage) or usage
        # A connection that breaks mid-stream surfaces as an HTTP error,
        # which the SDK does not wrap.
        except (OpenAIError, httpx2.HTTPError) as exc:
            raise LLMFailed(f"Chat stream from {self.model} failed") from exc
        if not received.strip():
            raise LLMFailed(f"{self.model} returned no text")
        if usage is not None:
            yield usage

    def _request(self, messages: Sequence[Message]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content}
                         for message in messages],
            self._max_tokens_parameter: self.max_tokens,
        }
        if self.temperature is not None:
            request["temperature"] = self.temperature
        return request

    async def aclose(self) -> None:
        await self._client.close()


def _preview(response: Any) -> str:
    """The start of a reply, for error messages."""
    text = response if isinstance(response, str) else repr(response)
    return " ".join(text.split())[:200]


def _usage(usage: Any) -> TokenUsage | None:
    if usage is None or usage.prompt_tokens is None or usage.completion_tokens is None:
        return None
    return TokenUsage(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)
