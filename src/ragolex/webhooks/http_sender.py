import asyncio
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx2

from ragolex.core.errors import WebhookFailed
from ragolex.core.network import is_public_address


class HTTPWebhookSender:
    """POSTs webhook deliveries.

    Unless ``allow_private``, the host is resolved first and every address
    it has must be public, so a webhook cannot reach this server's network
    (a database, a cloud metadata service). Redirects are not followed, for
    the same reason: a redirect counts as a failed attempt.
    """

    def __init__(self, *, allow_private: bool = False, timeout_seconds: float = 10.0,
                 http_client: httpx2.AsyncClient | None = None):
        self.allow_private = allow_private
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds,
                                                         follow_redirects=False)

    async def send(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        if not self.allow_private:
            await self._check_addresses(url)
        try:
            response = await self._client.post(url, content=body, headers=dict(headers))
        except httpx2.TimeoutException as exc:
            raise WebhookFailed("timed out") from exc
        except httpx2.HTTPError as exc:
            raise WebhookFailed("could not connect") from exc
        return response.status_code

    @staticmethod
    async def _check_addresses(url: str) -> None:
        host = urlsplit(url).hostname or ""
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None,
                                                                 type=socket.SOCK_STREAM)
        except OSError as exc:
            raise WebhookFailed(f"{host} could not be resolved") from exc
        if not all(is_public_address(str(info[4][0])) for info in infos):
            raise WebhookFailed(f"{host} is not a public address")

    async def aclose(self) -> None:
        await self._client.aclose()
