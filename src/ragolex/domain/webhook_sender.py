"""The interface webhook deliveries are sent through. The HTTP one is in ragolex.webhooks."""

from collections.abc import Mapping
from typing import Protocol


class WebhookSender(Protocol):

    async def send(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        """POST ``body`` to ``url`` and return the response's status code.

        Raises WebhookFailed when no response came (unreachable, timed out)
        or the URL is not one webhooks may reach.
        """
        ...

    async def aclose(self) -> None: ...
