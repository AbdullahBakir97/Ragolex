from collections.abc import Mapping
from typing import Any

import httpx2

from .http import ChatApi, split_text

# WhatsApp's limit for a text message's body.
MESSAGE_LIMIT = 4096


class GraphApi(ChatApi):

    def describe(self, body: Any) -> str | None:
        error = body.get("error") if isinstance(body, dict) else None
        return error.get("message") if isinstance(error, dict) else None


class WhatsAppPlatform:
    """The WhatsApp Business Cloud API (Meta's Graph API), with a phone number's id and
    an access token.

    Meta sends messages to the callback URL set in the app's WhatsApp
    settings, after checking it with the bot's verify token, and signs each
    with the app secret.
    """

    def __init__(self, *, timeout_seconds: float = 15.0,
                 http_client: httpx2.AsyncClient | None = None,
                 base_url: str = "https://graph.facebook.com/v21.0"):
        self.api = GraphApi(base_url, timeout_seconds, http_client)

    async def check(self, credentials: Mapping[str, str]) -> str:
        number = await self.api.request(
            "GET", f"/{credentials['phone_number_id']}", token=credentials["access_token"],
            params={"fields": "display_phone_number,verified_name"},
            # An unknown phone number id is a 400 or a 404.
            refused=(400, 401, 403, 404))
        name = number.get("verified_name") or "WhatsApp"
        return f"{name} ({number.get('display_phone_number', '?')})"

    async def register(self, credentials: Mapping[str, str], url: str, secret: str) -> None:
        """Set in the Meta app's WhatsApp settings instead: Callback URL and Verify token."""

    async def unregister(self, credentials: Mapping[str, str]) -> None:
        """Remove the callback URL in the Meta app's settings."""

    async def send(self, credentials: Mapping[str, str], reply_to: Mapping[str, str],
                   text: str) -> None:
        for number, piece in enumerate(split_text(text, MESSAGE_LIMIT)):
            payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": reply_to["to"],
                                       "type": "text",
                                       "text": {"body": piece, "preview_url": False}}
            if number == 0 and reply_to.get("message_id"):
                payload["context"] = {"message_id": reply_to["message_id"]}
            await self.api.request("POST", f"/{credentials['phone_number_id']}/messages",
                                   token=credentials["access_token"], json=payload)

    async def aclose(self) -> None:
        await self.api.aclose()
