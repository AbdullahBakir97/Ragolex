"""What chat apps send bots: checked to come from the app, and read into messages.

Each app proves a delivery its own way: Telegram sends the webhook's secret
token, Slack signs the body with the app's signing secret (with a
timestamp, against replays), and WhatsApp signs it with the app secret.
"""

import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ragolex.core.errors import BotSignatureInvalid
from ragolex.domain.models import Bot, IncomingMessage

# Slack refuses older signatures, so a captured request cannot be replayed later.
SLACK_MAX_AGE_SECONDS = 300
_SLACK_MENTION = re.compile(r"<@[A-Z0-9]+>")


@dataclass(frozen=True)
class Delivery:
    """The messages in a delivery, or the challenge an app checks the URL with."""

    messages: list[IncomingMessage] = field(default_factory=list)
    challenge: str | None = None


def _same(given: str | None, expected: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), expected.encode())


def _hmac(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        return None


def read_delivery(bot: Bot, headers: Mapping[str, str], body: bytes,
                  now: float | None = None) -> Delivery:
    """The delivery's messages; raises BotSignatureInvalid unless the app sent it."""
    if bot.kind == "telegram":
        return _telegram(bot, headers, body)
    if bot.kind == "slack":
        return _slack(bot, headers, body, time.time() if now is None else now)
    return _whatsapp(bot, headers, body)


def _telegram(bot: Bot, headers: Mapping[str, str], body: bytes) -> Delivery:
    if not _same(headers.get("x-telegram-bot-api-secret-token"), bot.webhook_secret):
        raise BotSignatureInvalid()
    update = _json(body)
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return Delivery()  # Photos, edits, members joining: nothing to answer.
    if message.get("from", {}).get("is_bot"):
        return Delivery()
    chat = str(message["chat"]["id"])
    return Delivery([IncomingMessage(
        update_id=str(update["update_id"]), chat_key=chat, text=message["text"],
        reply_to={"chat_id": chat, "message_id": str(message["message_id"])})])


def _slack(bot: Bot, headers: Mapping[str, str], body: bytes, now: float) -> Delivery:
    timestamp = headers.get("x-slack-request-timestamp", "")
    if not timestamp.isdigit() or abs(now - int(timestamp)) > SLACK_MAX_AGE_SECONDS:
        raise BotSignatureInvalid()
    expected = "v0=" + _hmac(bot.credentials["signing_secret"],
                             b"v0:" + timestamp.encode() + b":" + body)
    if not _same(headers.get("x-slack-signature"), expected):
        raise BotSignatureInvalid()
    payload = _json(body)
    if not isinstance(payload, dict):
        return Delivery()
    if payload.get("type") == "url_verification":
        return Delivery(challenge=str(payload.get("challenge", "")))
    event = payload.get("event")
    if payload.get("type") != "event_callback" or not isinstance(event, dict):
        return Delivery()
    # Mentions in channels, and direct messages; never the bot's own messages, or edits.
    direct = event.get("type") == "message" and event.get("channel_type") == "im"
    if (event.get("type") != "app_mention" and not direct) or event.get("bot_id") \
            or event.get("subtype") or not isinstance(event.get("text"), str):
        return Delivery()
    channel = str(event["channel"])
    thread = str(event.get("thread_ts") or event["ts"])
    text = _SLACK_MENTION.sub("", event["text"]).strip()
    # A direct message keeps one conversation; a mention in a channel, one per thread.
    reply_to = {"channel": channel} if direct and not event.get("thread_ts") else {
        "channel": channel, "thread_ts": thread}
    return Delivery([IncomingMessage(
        update_id=str(payload.get("event_id") or event["ts"]),
        chat_key=channel if direct else f"{channel}:{thread}", text=text, reply_to=reply_to)])


def _whatsapp(bot: Bot, headers: Mapping[str, str], body: bytes) -> Delivery:
    expected = "sha256=" + _hmac(bot.credentials["app_secret"], body)
    if not _same(headers.get("x-hub-signature-256"), expected):
        raise BotSignatureInvalid()
    payload = _json(body)
    messages = []
    for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if value.get("metadata", {}).get("phone_number_id") not in (
                    None, bot.credentials["phone_number_id"]):
                continue  # Another number of the same app.
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                sender = str(message["from"])
                messages.append(IncomingMessage(
                    update_id=str(message["id"]), chat_key=sender,
                    text=str(message["text"]["body"]),
                    reply_to={"to": sender, "message_id": str(message["id"])}))
    return Delivery(messages)


def whatsapp_challenge(bot: Bot, params: Mapping[str, str]) -> str:
    """The challenge to echo when Meta checks the callback URL with the verify token."""
    if params.get("hub.mode") != "subscribe" or not _same(params.get("hub.verify_token"),
                                                          bot.webhook_secret):
        raise BotSignatureInvalid()
    return params.get("hub.challenge", "")
