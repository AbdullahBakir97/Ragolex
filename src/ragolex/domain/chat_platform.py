"""The interface bots talk to chat apps through. The HTTP ones are in ragolex.bots."""

from collections.abc import Mapping
from typing import Protocol


class ChatPlatform(Protocol):
    """One chat app (Telegram, Slack or WhatsApp), for every bot on it.

    Each call gets the bot's credentials. Raises BotPlatformFailed when the
    app refused the call or could not be reached; its message says why.
    """

    async def check(self, credentials: Mapping[str, str]) -> str:
        """The bot's name in the app (such as @acme_help_bot), once the app accepts them."""
        ...

    async def register(self, credentials: Mapping[str, str], url: str, secret: str) -> None:
        """Have the app send the bot's messages to ``url``, if it is set up by API."""
        ...

    async def unregister(self, credentials: Mapping[str, str]) -> None:
        """Stop the app sending the bot's messages, if it was set up by API."""
        ...

    async def send(self, credentials: Mapping[str, str], reply_to: Mapping[str, str],
                   text: str) -> None:
        """Send ``text`` to the chat (or thread) an incoming message came from."""
        ...

    async def aclose(self) -> None: ...
