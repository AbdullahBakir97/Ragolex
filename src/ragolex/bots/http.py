"""What the chat apps' clients share: calling their HTTP APIs, and splitting long text."""

from collections.abc import Mapping
from typing import Any

import httpx2

from ragolex.core.errors import BotCredentialsInvalid, BotPlatformFailed


class ChatApi:
    """A chat app's HTTP API. Errors become BotPlatformFailed, or BotCredentialsInvalid
    when the app refuses the credentials; neither carries a token."""

    def __init__(self, base_url: str, timeout_seconds: float,
                 http_client: httpx2.AsyncClient | None):
        self.base_url = base_url
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds,
                                                         follow_redirects=False)

    async def request(self, method: str, path: str, *, token: str | None = None,
                      json: Mapping[str, Any] | None = None,
                      params: Mapping[str, str] | None = None,
                      refused: tuple[int, ...] = (401, 403)) -> Any:
        """The response's JSON. ``refused`` are the statuses that mean the credentials
        are wrong (checking them, a 404 for an unknown token or id too)."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = await self._client.request(method, self.base_url + path, json=json,
                                                  params=params, headers=headers)
        except httpx2.TimeoutException as exc:
            raise BotPlatformFailed("timed out") from exc
        except httpx2.HTTPError as exc:
            raise BotPlatformFailed("could not connect") from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code in refused:
            raise BotCredentialsInvalid(self.describe(body) or "the credentials were refused")
        if response.status_code >= 400:
            raise BotPlatformFailed(self.describe(body) or f"status {response.status_code}")
        return body

    def describe(self, body: Any) -> str | None:
        """The app's own words for an error, from its response body."""
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


def split_text(text: str, limit: int) -> list[str]:
    """``text`` in pieces of at most ``limit`` characters, cut between paragraphs or
    lines where it can, so a long answer arrives as several messages."""
    pieces: list[str] = []
    rest = text.strip()
    while len(rest) > limit:
        cut = max(rest.rfind("\n\n", 0, limit), rest.rfind("\n", 0, limit))
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces
