from collections.abc import Mapping
from typing import Any

import httpx2

from ragolex.core.errors import BotCredentialsInvalid, BotPlatformFailed

from .http import ChatApi, split_text

# Slack takes more, but long messages are easier to read in pieces.
MESSAGE_LIMIT = 3900
_REFUSED = {"invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired"}


class SlackApi(ChatApi):

    def describe(self, body: Any) -> str | None:
        return body.get("error") if isinstance(body, dict) else None


class SlackPlatform:
    """Slack's Web API, with the app's bot token (xoxb-…).

    Slack sends events to the URL set in the app's Event Subscriptions, and
    signs each with the app's signing secret; there is no webhook to set.
    """

    def __init__(self, *, timeout_seconds: float = 15.0,
                 http_client: httpx2.AsyncClient | None = None,
                 base_url: str = "https://slack.com/api"):
        self.api = SlackApi(base_url, timeout_seconds, http_client)

    async def _call(self, credentials: Mapping[str, str], method: str,
                    payload: Mapping[str, Any]) -> dict:
        body = await self.api.request("POST", f"/{method}", token=credentials["bot_token"],
                                      json=payload)
        if not isinstance(body, dict) or not body.get("ok"):
            error = self.api.describe(body) or "unexpected reply"
            raise (BotCredentialsInvalid if error in _REFUSED else BotPlatformFailed)(error)
        return body

    async def check(self, credentials: Mapping[str, str]) -> str:
        me = await self._call(credentials, "auth.test", {})
        return f"@{me.get('user')} in {me.get('team')}"

    async def register(self, credentials: Mapping[str, str], url: str, secret: str) -> None:
        """Set in the Slack app's settings instead: Event Subscriptions › Request URL."""

    async def unregister(self, credentials: Mapping[str, str]) -> None:
        """Remove the Request URL in the Slack app's settings."""

    async def send(self, credentials: Mapping[str, str], reply_to: Mapping[str, str],
                   text: str) -> None:
        for piece in split_text(text, MESSAGE_LIMIT):
            payload: dict[str, Any] = {"channel": reply_to["channel"], "text": piece,
                                       "unfurl_links": False}
            if reply_to.get("thread_ts"):
                payload["thread_ts"] = reply_to["thread_ts"]
            await self._call(credentials, "chat.postMessage", payload)

    async def aclose(self) -> None:
        await self.api.aclose()
