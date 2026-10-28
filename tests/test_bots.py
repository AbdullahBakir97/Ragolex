"""Bots: a project's assistant in Telegram, Slack and WhatsApp."""

import asyncio
import hashlib
import hmac
import json
import time

import httpx2
import pytest

from ragolex.api.dependencies import get_chat_platforms
from ragolex.bots.http import split_text
from ragolex.bots.inbound import read_delivery, whatsapp_challenge
from ragolex.bots.slack import SlackPlatform
from ragolex.bots.telegram import TelegramPlatform
from ragolex.bots.whatsapp import WhatsAppPlatform
from ragolex.core.config import get_settings
from ragolex.core.errors import (
    BotCredentialsInvalid,
    BotPlatformFailed,
    BotSignatureInvalid,
)
from ragolex.domain.models import BOT_KINDS, Bot
from ragolex.services.bot_service import (
    FAILED,
    LIMIT_REACHED,
    NEW_CONVERSATION,
    NO_ANSWER,
    SLOW_DOWN,
    reply_text,
)

from .fakes import FakeChatPlatform
from .test_ask_api import upload_process_and_index

QUESTION = "Where is the embedding vector stored?"
TELEGRAM = {"token": "123456:secret-token"}
SLACK = {"bot_token": "xoxb-1", "signing_secret": "slack-signing"}
WHATSAPP = {"access_token": "EAAG", "phone_number_id": "1055", "app_secret": "meta-secret"}


@pytest.fixture
def platforms(client, embedder, llm):
    """Stand-in chat apps, and the models the bots answer with after the response."""
    fakes = {kind: FakeChatPlatform(f"@{kind}_bot") for kind in BOT_KINDS}
    client.app.dependency_overrides[get_chat_platforms] = lambda: fakes
    client.app.state.chat_platforms = fakes
    client.app.state.embedder, client.app.state.llm = embedder, llm
    upload_process_and_index(client, project="demo")
    return fakes


def add_bot(client, kind="telegram", credentials=TELEGRAM, **fields):
    return client.post("/api/v1/projects/demo/bots",
                       json={"kind": kind, "name": "Help desk", "credentials": credentials,
                             **fields})


def telegram_update(update_id=1, text=QUESTION, chat=42, **message):
    return {"update_id": update_id,
            "message": {"message_id": 100 + update_id, "chat": {"id": chat},
                        "from": {"id": 7, "is_bot": False}, "text": text, **message}}


def deliver(client, bot, payload, secret=None):
    return client.post(f"/api/v1/bots/{bot['id']}/webhook", content=json.dumps(payload),
                       headers={"X-Telegram-Bot-Api-Secret-Token":
                                secret or bot_secret(client, bot)})


def bot_secret(client, bot):
    return client.app.state.chat_platforms["telegram"].registered["secret"]


def slack_headers(body: bytes, secret="slack-signing", timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body,
                         hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": f"v0={signature}"}


def whatsapp_headers(body: bytes, secret="meta-secret"):
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={signature}"}


# Managing bots


def test_a_telegram_bot_is_checked_registered_and_listed(client, platforms, query):
    created = add_bot(client, tags=["Guides"])

    assert created.status_code == 201
    bot = created.json()
    assert (bot["kind"], bot["account"], bot["tags"], bot["enabled"]) == (
        "telegram", "@telegram_bot", ["guides"], True)
    assert bot["webhook_url"] == f"http://localhost:3000/api/v1/bots/{bot['id']}/webhook"
    assert bot["verify_token"] is None and "credentials" not in bot
    telegram = platforms["telegram"]
    assert telegram.registered["url"] == bot["webhook_url"]
    assert len(telegram.registered["secret"]) >= 32
    assert [b["id"] for b in client.get("/api/v1/projects/demo/bots").json()["items"]] == [
        bot["id"]]
    assert client.get(f"/api/v1/projects/demo/bots/{bot['id']}").json()["name"] == "Help desk"
    stored = query("SELECT credentials FROM bots")[0][0]
    assert json.loads(stored) == TELEGRAM  # Encrypted when ENCRYPTION_KEYS is set.
    event = client.get("/api/v1/audit?action=bot").json()["items"][0]
    assert event["action"] == "bot.created" and "token" not in json.dumps(event)


def test_whatsapp_bots_show_their_verify_token(client, platforms):
    bot = add_bot(client, "whatsapp", WHATSAPP).json()

    assert bot["verify_token"] and bot["account"] == "@whatsapp_bot"
    assert platforms["whatsapp"].registered["secret"] == bot["verify_token"]


def test_bots_that_cannot_be_added(client, platforms):
    missing = add_bot(client, "slack", {"bot_token": "xoxb-1"})
    assert (missing.status_code, missing.json()) == (422, {"signal": "bot_credentials_invalid"})
    assert add_bot(client, "discord").status_code == 422
    assert add_bot(client, name=" ").status_code == 422
    platforms["telegram"].refuse = "Unauthorized"
    refused = add_bot(client)
    assert (refused.status_code, refused.json()) == (502, {"signal": "bot_platform_failed"})
    assert client.get("/api/v1/projects/demo/bots").json()["items"] == []
    unknown = client.post("/api/v1/projects/nothing/bots",
                          json={"kind": "telegram", "name": "X", "credentials": TELEGRAM})
    assert unknown.json() == {"signal": "project_not_found"}


def test_bots_are_changed_and_removed(client, platforms):
    bot = add_bot(client).json()
    path = f"/api/v1/projects/demo/bots/{bot['id']}"

    changed = client.patch(path, json={"name": "Support", "tags": [], "enabled": False})
    assert (changed.json()["name"], changed.json()["enabled"]) == ("Support", False)
    platforms["telegram"].account = "@renamed_bot"
    renewed = client.patch(path, json={"credentials": {"token": "654321:new"}})
    assert renewed.json()["account"] == "@renamed_bot"
    assert client.patch(path, json={"enabled": None}).status_code == 422
    event = client.get("/api/v1/audit?action=bot.updated").json()["items"][0]
    assert event["details"]["credentials"] == "replaced"

    assert client.delete(path).status_code == 204
    assert platforms["telegram"].unregistered == 1
    gone = client.get(path)
    assert (gone.status_code, gone.json()) == (404, {"signal": "bot_not_found"})


def test_a_bot_goes_even_when_its_app_refuses_to_stop(client, platforms):
    bot = add_bot(client).json()
    platforms["telegram"].refuse = "Unauthorized"

    assert client.delete(f"/api/v1/projects/demo/bots/{bot['id']}").status_code == 204


# Answering


def test_a_telegram_question_is_answered_in_its_chat_with_sources(client, platforms, query):
    bot = add_bot(client).json()

    response = deliver(client, bot, telegram_update())

    assert response.status_code == 200
    [(reply_to, text)] = platforms["telegram"].sent
    assert reply_to == {"chat_id": "42", "message_id": "101"}
    assert text.startswith("Each chunk gets an embedding vector [1].")
    assert "Sources:\n[1] guide.txt" in text
    [listed] = client.get("/api/v1/projects/demo/bots").json()["items"]
    assert listed["last_message_at"] is not None and listed["last_error"] is None
    assert query("SELECT count(*) FROM conversations") == [(1,)]


def test_a_chat_keeps_its_conversation_until_new(client, platforms, query, llm):
    bot = add_bot(client).json()

    deliver(client, bot, telegram_update(1))
    deliver(client, bot, telegram_update(2, text="And where is it kept?"))
    assert query("SELECT count(*) FROM conversations") == [(1,)]
    assert query("SELECT count(*) FROM conversation_messages") == [(4,)]

    deliver(client, bot, telegram_update(3, text="/new@telegram_bot"))
    deliver(client, bot, telegram_update(4))
    assert platforms["telegram"].sent[2][1] == NEW_CONVERSATION
    assert query("SELECT count(*) FROM conversations") == [(2,)]
    # Another chat has its own.
    deliver(client, bot, telegram_update(5, chat=43))
    assert query("SELECT count(*) FROM conversations") == [(3,)]


def test_a_delivery_sent_again_is_answered_once(client, platforms):
    bot = add_bot(client).json()

    deliver(client, bot, telegram_update(1))
    deliver(client, bot, telegram_update(1))

    assert len(platforms["telegram"].sent) == 1


def test_a_chat_that_sends_too_much_is_asked_to_slow_down_once(client, platforms, llm,
                                                              monkeypatch):
    monkeypatch.setenv("BOT_CHAT_MESSAGES_PER_MINUTE", "2")
    get_settings.cache_clear()
    bot = add_bot(client).json()

    deliver(client, bot, telegram_update(1))
    deliver(client, bot, telegram_update(2))
    calls = len(llm.calls)
    for update in range(3, 6):
        deliver(client, bot, telegram_update(update))

    replies = [text for _, text in platforms["telegram"].sent]
    assert len(replies) == 3 and replies[2] == SLOW_DOWN
    assert len(llm.calls) == calls  # The model was not asked past the limit.
    # Other chats are not slowed down.
    deliver(client, bot, telegram_update(6, chat=43))
    assert len(platforms["telegram"].sent) == 4
    get_settings.cache_clear()


def test_old_deliveries_are_forgotten(client, platforms, query, monkeypatch, db):
    monkeypatch.setattr("ragolex.persistence.repositories.PRUNE_DELIVERIES_CHANCE", 1.0)
    bot = add_bot(client).json()
    deliver(client, bot, telegram_update(1))
    asyncio.run(_age_deliveries(db))

    deliver(client, bot, telegram_update(2))

    assert query("SELECT update_id FROM bot_deliveries") == [("2",)]


async def _age_deliveries(url):
    from sqlalchemy import text as sql

    from ragolex.persistence.database import create_engine

    engine = create_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sql("UPDATE bot_deliveries SET created_at = now() - interval '8 days'"))
    finally:
        await engine.dispose()


def test_start_says_what_the_bot_does(client, platforms, llm):
    bot = add_bot(client).json()

    deliver(client, bot, telegram_update(text="/start"))

    assert "answer questions from the documents of demo" in platforms["telegram"].sent[0][1]
    assert llm.calls == []


def test_deliveries_not_from_the_app_are_refused(client, platforms):
    bot = add_bot(client).json()

    forged = deliver(client, bot, telegram_update(), secret="guessed")

    assert (forged.status_code, forged.json()) == (401, {"signal": "bot_signature_invalid"})
    assert platforms["telegram"].sent == []
    missing = client.post("/api/v1/bots/bot_aaaaaaaaaaaaaaaaaaaaaa/webhook", content=b"{}")
    assert (missing.status_code, missing.json()) == (404, {"signal": "bot_not_found"})
    huge = client.post(f"/api/v1/bots/{bot['id']}/webhook", content=b"x" * 1_000_001)
    assert huge.status_code == 413
    # Sent in pieces with no length given, it is cut off once past the limit too.
    streamed = client.post(f"/api/v1/bots/{bot['id']}/webhook",
                           content=(b"x" * 100_000 for _ in range(20)))
    assert streamed.status_code == 413


def test_a_bot_turned_off_ignores_messages(client, platforms):
    bot = add_bot(client).json()
    client.patch(f"/api/v1/projects/demo/bots/{bot['id']}", json={"enabled": False})

    assert deliver(client, bot, telegram_update()).status_code == 200

    assert platforms["telegram"].sent == []


def test_failures_are_answered_with_an_apology_and_noted(client, platforms, llm):
    bot = add_bot(client).json()
    llm.fail = True

    deliver(client, bot, telegram_update())

    assert platforms["telegram"].sent[0][1] == FAILED
    [listed] = client.get("/api/v1/projects/demo/bots").json()["items"]
    assert listed["last_error"] == "llm_failed"


def test_a_tenants_limits_apply_to_bots(client, platforms, monkeypatch):
    monkeypatch.setenv("ANSWERS_PER_MONTH", "1")
    get_settings.cache_clear()
    bot = add_bot(client).json()

    deliver(client, bot, telegram_update(1))
    deliver(client, bot, telegram_update(2))

    assert platforms["telegram"].sent[1][1] == LIMIT_REACHED


def test_a_reply_that_cannot_be_sent_is_noted(client, platforms):
    bot = add_bot(client).json()
    platforms["telegram"].refuse = "Forbidden: bot was blocked by the user"

    deliver(client, bot, telegram_update())

    [listed] = client.get("/api/v1/projects/demo/bots").json()["items"]
    assert listed["last_error"] == "Sending the reply failed: Forbidden: bot was blocked by the user"


def test_slack_mentions_are_answered_in_their_thread(client, platforms):
    bot = add_bot(client, "slack", SLACK).json()
    url = f"/api/v1/bots/{bot['id']}/webhook"
    challenge = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()

    assert client.post(url, content=challenge, headers=slack_headers(challenge)).json() == {
        "challenge": "abc"}
    event = json.dumps({"type": "event_callback", "event_id": "Ev1", "event": {
        "type": "app_mention", "channel": "C1", "ts": "1700.1",
        "text": f"<@U0BOT> {QUESTION}"}}).encode()
    assert client.post(url, content=event, headers=slack_headers(event)).status_code == 200

    [(reply_to, text)] = platforms["slack"].sent
    assert reply_to == {"channel": "C1", "thread_ts": "1700.1"}
    assert "[1] guide.txt" in text
    forged = client.post(url, content=event, headers=slack_headers(event, secret="wrong"))
    assert forged.status_code == 401


def test_whatsapp_checks_the_callback_and_answers_messages(client, platforms):
    bot = add_bot(client, "whatsapp", WHATSAPP).json()
    url = f"/api/v1/bots/{bot['id']}/webhook"

    check = client.get(url, params={"hub.mode": "subscribe", "hub.challenge": "1158201444",
                                    "hub.verify_token": bot["verify_token"]})
    assert (check.status_code, check.text) == (200, "1158201444")
    assert client.get(url, params={"hub.mode": "subscribe", "hub.challenge": "x",
                                   "hub.verify_token": "wrong"}).status_code == 401
    body = json.dumps({"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "1055"},
        "messages": [{"id": "wamid.1", "from": "4915112345678", "type": "text",
                      "text": {"body": QUESTION}}]}}]}]}).encode()

    assert client.post(url, content=body, headers=whatsapp_headers(body)).status_code == 200

    [(reply_to, text)] = platforms["whatsapp"].sent
    assert reply_to == {"to": "4915112345678", "message_id": "wamid.1"}
    telegram = add_bot(client).json()
    not_whatsapp = client.get(f"/api/v1/bots/{telegram['id']}/webhook")
    assert not_whatsapp.status_code == 401


def test_the_export_lists_bots_without_their_credentials(client, platforms):
    add_bot(client)

    import io
    import zipfile
    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/v1/export").content))
    [bot] = json.loads(archive.read("projects/demo/bots.json"))

    assert (bot["kind"], bot["account"]) == ("telegram", "@telegram_bot")
    assert "credentials" not in bot and "webhook_secret" not in bot
    assert "secret-token" not in archive.read("projects/demo/bots.json").decode()


def test_webhooks_stay_on_this_server_even_with_a_domain(client, platforms):
    from ragolex import cli
    assert cli.main(["domains", "add", "help.example.com", "--tenant", "default",
                     "--verified"]) == 0

    bot = add_bot(client).json()

    # Messages carry the bot's secret: never to a domain that may pass to someone else.
    assert bot["webhook_url"].startswith("http://localhost:3000/api/v1/bots/")


# Reading deliveries


def bot(kind, credentials, secret="hook-secret"):
    from datetime import UTC, datetime
    return Bot(id="bot_x", tenant_id=1, tenant_name="default", project_id=1,
               project_name="demo", kind=kind, name="Help", account="@help",
               credentials=credentials, webhook_secret=secret, enabled=True,
               created_at=datetime.now(UTC))


def test_telegram_deliveries_without_text_are_not_answered():
    telegram = bot("telegram", TELEGRAM)
    headers = {"x-telegram-bot-api-secret-token": "hook-secret"}

    for update in [{"update_id": 1, "edited_message": {}},
                   telegram_update(text=None),
                   telegram_update(**{"from": {"id": 1, "is_bot": True}}),
                   "not json"]:
        body = update.encode() if isinstance(update, str) else json.dumps(update).encode()
        assert read_delivery(telegram, headers, body).messages == []
    with pytest.raises(BotSignatureInvalid):
        read_delivery(telegram, {}, b"{}")


def test_slack_direct_messages_keep_one_conversation_and_old_signatures_fail():
    slack = bot("slack", SLACK)
    now = time.time()

    def event(**fields):
        body = json.dumps({"type": "event_callback", "event_id": "Ev2", "event": {
            "channel": "D1", "ts": "1.2", "text": "hi", **fields}}).encode()
        return read_delivery(slack, {k.lower(): v for k, v in slack_headers(body).items()},
                             body, now).messages

    [direct] = event(type="message", channel_type="im")
    assert (direct.chat_key, dict(direct.reply_to)) == ("D1", {"channel": "D1"})
    [threaded] = event(type="message", channel_type="im", thread_ts="1.0")
    assert (threaded.chat_key, threaded.reply_to["thread_ts"]) == ("D1", "1.0")
    # Channel messages without a mention, the bot's own, and edits are not for it.
    assert event(type="message", channel_type="channel") == []
    assert event(type="app_mention", bot_id="B1") == []
    assert event(type="message", channel_type="im", subtype="message_changed") == []
    old = json.dumps({"type": "event_callback"}).encode()
    headers = {k.lower(): v for k, v in slack_headers(old, timestamp=now - 301).items()}
    with pytest.raises(BotSignatureInvalid):
        read_delivery(slack, headers, old, now)


def test_whatsapp_reads_only_its_numbers_text_messages():
    whatsapp = bot("whatsapp", WHATSAPP)
    body = json.dumps({"entry": [{"changes": [
        {"value": {"metadata": {"phone_number_id": "1055"}, "messages": [
            {"id": "a", "from": "49", "type": "text", "text": {"body": "one"}},
            {"id": "b", "from": "49", "type": "image"},
            {"id": "c", "from": "50", "type": "text", "text": {"body": "two"}}]}},
        {"value": {"metadata": {"phone_number_id": "9999"}, "messages": [
            {"id": "d", "from": "51", "type": "text", "text": {"body": "other"}}]}},
        {"value": {"statuses": [{"id": "a", "status": "read"}]}}]}]}).encode()

    messages = read_delivery(whatsapp, {k.lower(): v for k, v in whatsapp_headers(body).items()},
                             body).messages

    assert [(m.update_id, m.chat_key, m.text) for m in messages] == [
        ("a", "49", "one"), ("c", "50", "two")]
    with pytest.raises(BotSignatureInvalid):
        read_delivery(whatsapp, {"x-hub-signature-256": "sha256=0"}, body)
    with pytest.raises(BotSignatureInvalid):
        whatsapp_challenge(whatsapp, {"hub.mode": "unsubscribe", "hub.verify_token": "hook-secret"})


# Talking to the chat apps


def api(handler):
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.mark.anyio
async def test_telegram_calls_its_bot_api():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content or b"{}")))
        if request.url.path.endswith("/getMe"):
            return httpx2.Response(200, json={"ok": True, "result": {"username": "acme_bot"}})
        return httpx2.Response(200, json={"ok": True, "result": True})

    telegram = TelegramPlatform(http_client=api(handler))
    assert await telegram.check(TELEGRAM) == "@acme_bot"
    await telegram.register(TELEGRAM, "https://rag.example.com/hook", "s3cret")
    await telegram.send(TELEGRAM, {"chat_id": "42", "message_id": "7"}, "a" * 5000)
    await telegram.unregister(TELEGRAM)

    paths = [path.rsplit("/", 1)[1] for path, _ in calls]
    assert paths == ["getMe", "setWebhook", "sendMessage", "sendMessage", "deleteWebhook"]
    assert calls[0][0] == "/bot123456:secret-token/getMe"
    assert calls[1][1] == {"url": "https://rag.example.com/hook", "secret_token": "s3cret",
                           "allowed_updates": ["message"]}
    first, second = calls[2][1], calls[3][1]
    assert first["reply_parameters"]["message_id"] == 7 and "reply_parameters" not in second
    assert len(first["text"]) == 4096 and len(second["text"]) == 904
    await telegram.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(("response", "error"), [
    (httpx2.Response(401, json={"ok": False, "description": "Unauthorized"}), BotCredentialsInvalid),
    (httpx2.Response(404, json={"ok": False, "description": "Not Found"}), BotCredentialsInvalid),
    (httpx2.Response(502, text="Bad gateway"), BotPlatformFailed),
    (httpx2.Response(200, json={"ok": False, "description": "Too Many Requests"}), BotPlatformFailed),
])
async def test_telegram_errors(response, error):
    telegram = TelegramPlatform(http_client=api(lambda request: response))

    with pytest.raises(error):
        await telegram.check(TELEGRAM)


@pytest.mark.anyio
async def test_unreachable_apps_fail_without_their_tokens():
    def down(request):
        raise httpx2.ConnectError("refused")

    def slow(request):
        raise httpx2.ReadTimeout("slow")

    for handler, message in [(down, "could not connect"), (slow, "timed out")]:
        with pytest.raises(BotPlatformFailed) as caught:
            await TelegramPlatform(http_client=api(handler)).send(TELEGRAM, {"chat_id": "1"}, "x")
        assert str(caught.value) == message


@pytest.mark.anyio
async def test_slack_calls_its_web_api():
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers["authorization"],
                      json.loads(request.content or b"{}")))
        if request.url.path.endswith("auth.test"):
            return httpx2.Response(200, json={"ok": True, "user": "helper", "team": "Acme"})
        return httpx2.Response(200, json={"ok": True})

    slack = SlackPlatform(http_client=api(handler))
    assert await slack.check(SLACK) == "@helper in Acme"
    await slack.register(SLACK, "https://x", "y")
    await slack.unregister(SLACK)
    await slack.send(SLACK, {"channel": "C1", "thread_ts": "1.0"}, "Hello")

    assert calls[1] == ("/api/chat.postMessage", "Bearer xoxb-1",
                        {"channel": "C1", "text": "Hello", "unfurl_links": False,
                         "thread_ts": "1.0"})
    refused = SlackPlatform(http_client=api(
        lambda request: httpx2.Response(200, json={"ok": False, "error": "invalid_auth"})))
    with pytest.raises(BotCredentialsInvalid):
        await refused.check(SLACK)
    failing = SlackPlatform(http_client=api(
        lambda request: httpx2.Response(200, json={"ok": False, "error": "channel_not_found"})))
    with pytest.raises(BotPlatformFailed, match="channel_not_found"):
        await failing.send(SLACK, {"channel": "C9"}, "x")


@pytest.mark.anyio
async def test_whatsapp_calls_the_graph_api():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.url.params.get("fields"),
                      json.loads(request.content or b"{}")))
        if request.method == "GET":
            return httpx2.Response(200, json={"display_phone_number": "+49 151",
                                              "verified_name": "Acme"})
        return httpx2.Response(200, json={"messages": [{"id": "wamid.2"}]})

    whatsapp = WhatsAppPlatform(http_client=api(handler))
    assert await whatsapp.check(WHATSAPP) == "Acme (+49 151)"
    await whatsapp.register(WHATSAPP, "https://x", "y")
    await whatsapp.unregister(WHATSAPP)
    await whatsapp.send(WHATSAPP, {"to": "49", "message_id": "wamid.1"}, "Hi")

    assert calls[0][:3] == ("GET", "/v21.0/1055", "display_phone_number,verified_name")
    assert calls[1][3] == {"messaging_product": "whatsapp", "to": "49", "type": "text",
                           "text": {"body": "Hi", "preview_url": False},
                           "context": {"message_id": "wamid.1"}}
    unknown = WhatsAppPlatform(http_client=api(lambda request: httpx2.Response(
        400, json={"error": {"message": "Unsupported get request"}})))
    with pytest.raises(BotCredentialsInvalid, match="Unsupported get request"):
        await unknown.check(WHATSAPP)
    with pytest.raises(BotPlatformFailed, match="Unsupported get request"):
        await unknown.send(WHATSAPP, {"to": "49"}, "x")


def test_long_text_is_split_between_paragraphs():
    text = "First paragraph.\n\nSecond one, longer.\nWith a line."

    assert split_text(text, 30) == ["First paragraph.", "Second one, longer.", "With a line."]
    assert split_text("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]
    assert split_text("one two three", 8) == ["one two", "three"]
    assert split_text("  ", 10) == []


def test_answers_without_text_say_so():
    from ragolex.services.answer_service import Answer
    empty = Answer(text=None, citations=[], prompt_version="v1", usage=None, cost_usd=None)

    assert reply_text(empty, {}) == NO_ANSWER


def test_without_a_model_a_bot_says_sorry_but_commands_still_work(client, platforms):
    bot = add_bot(client).json()
    client.app.state.llm = None

    deliver(client, bot, telegram_update(1, text="/start"))
    deliver(client, bot, telegram_update(2))
    client.app.state.embedder = None
    deliver(client, bot, telegram_update(3))

    replies = [text for _, text in platforms["telegram"].sent]
    assert replies[0].startswith("Hello!") and replies[1:] == [FAILED, FAILED]
    [listed] = client.get("/api/v1/projects/demo/bots").json()["items"]
    assert listed["last_error"] == "embedding_not_configured"


def test_a_failure_outside_the_answer_is_logged(client, platforms, caplog, monkeypatch):
    bot = add_bot(client).json()

    async def broken(*args, **kwargs):
        raise RuntimeError("database gone")
    monkeypatch.setattr("ragolex.services.bot_service.BotService.respond", broken)

    assert deliver(client, bot, telegram_update()).status_code == 200
    assert "a message could not be answered" in caplog.text
