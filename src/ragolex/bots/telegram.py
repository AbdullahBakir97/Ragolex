from collections.abc import Mapping
from typing import Any

import httpx2

from ragolex.core.errors import BotPlatformFailed

from .http import ChatApi, split_text

# Telegram's limit for one message.
MESSAGE_LIMIT = 4096


class TelegramApi(ChatApi):

    def describe(self, body: Any) -> str | None:
        return body.get("description") if isinstance(body, dict) else None


class TelegramPlatform:
    """Telegram's Bot API: the bot's token is all it needs, and its webhook is set by API.

    Telegram sends the webhook's secret in X-Telegram-Bot-Api-Secret-Token
    with every update, which is how deliveries are checked.
    """

    def __init__(self, *, timeout_seconds: float = 15.0,
                 http_client: httpx2.AsyncClient | None = None,
                 base_url: str = "https://api.telegram.org"):
        self.api = TelegramApi(base_url, timeout_seconds, http_client)

    async def _call(self, credentials: Mapping[str, str], method: str,
                    payload: Mapping[str, Any], refused: tuple[int, ...] = (401, 403)) -> Any:
        body = await self.api.request("POST", f"/bot{credentials['token']}/{method}",
                                      json=payload, refused=refused)
        if not isinstance(body, dict) or not body.get("ok"):
            raise BotPlatformFailed(self.api.describe(body) or "unexpected reply")
        return body.get("result")

    async def check(self, credentials: Mapping[str, str]) -> str:
        # A malformed token is a 404 from Telegram.
        me = await self._call(credentials, "getMe", {}, refused=(401, 403, 404))
        return f"@{me['username']}"

    async def register(self, credentials: Mapping[str, str], url: str, secret: str) -> None:
        await self._call(credentials, "setWebhook", {
            "url": url, "secret_token": secret, "allowed_updates": ["message"]})

    async def unregister(self, credentials: Mapping[str, str]) -> None:
        await self._call(credentials, "deleteWebhook", {})

    async def send(self, credentials: Mapping[str, str], reply_to: Mapping[str, str],
                   text: str) -> None:
        for number, piece in enumerate(split_text(text, MESSAGE_LIMIT)):
            payload: dict[str, Any] = {"chat_id": reply_to["chat_id"], "text": piece,
                                       "link_preview_options": {"is_disabled": True}}
            if number == 0 and reply_to.get("message_id"):
                payload["reply_parameters"] = {"message_id": int(reply_to["message_id"]),
                                               "allow_sending_without_reply": True}
            await self._call(credentials, "sendMessage", payload)

    async def aclose(self) -> None:
        await self.api.aclose()
