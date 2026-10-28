"""A project's assistants in chat apps: Telegram, Slack and WhatsApp.

A bot answers what people ask it from the project's documents, as the chat
widget does: each chat (or Slack thread) keeps a conversation, so
follow-ups work, and each answer lists its sources. Chat apps deliver
messages to the bot's webhook, which answers at once and replies later
(``respond``), since an answer takes longer than the apps wait.
"""

import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ragolex.core.errors import (
    AnswerQuotaExceeded,
    AppError,
    BotCredentialsInvalid,
    BotNotFound,
    BudgetExceeded,
    ProjectNotFound,
    RateLimited,
)
from ragolex.domain.chat_platform import ChatPlatform
from ragolex.domain.models import Bot, IncomingMessage, Project, SearchFilters
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.answer_service import Answer, AnswerService
from ragolex.services.audit import record
from ragolex.services.limit_service import LimitService
from ragolex.services.tag_service import clean_tags

logger = logging.getLogger(__name__)

BOT_PREFIX = "bot_"
# What each chat app's credentials hold.
CREDENTIALS = {
    "telegram": ("token",),
    "slack": ("bot_token", "signing_secret"),
    "whatsapp": ("access_token", "phone_number_id", "app_secret"),
}
TOP_K = 5
NO_ANSWER = "I could not find the answer to that in the documents."
NEW_CONVERSATION = "Starting a new conversation. What would you like to know?"
LIMIT_REACHED = "I cannot answer more questions right now: this assistant's limit is reached."
SLOW_DOWN = "That is a lot of questions at once. Please wait a minute, then ask again."
FAILED = "Sorry, something went wrong while answering. Please try again later."


def welcome(bot: Bot) -> str:
    return (f"Hello! I answer questions from the documents of {bot.project_name}, with my "
            f"sources. Ask me anything; send /new to start a new conversation.")


def clean_credentials(kind: str, credentials: Mapping[str, Any]) -> dict[str, str]:
    """The credentials the chat app needs, trimmed; raises BotCredentialsInvalid when one
    is missing."""
    cleaned = {name: str(credentials.get(name) or "").strip() for name in CREDENTIALS[kind]}
    missing = [name for name, value in cleaned.items() if not value]
    if missing:
        raise BotCredentialsInvalid(f"Missing: {', '.join(missing)}")
    return cleaned


def reply_text(answer: Answer, names: Mapping[str, str | None]) -> str:
    """An answer as a chat message: its text, then the sources its [n] markers cite."""
    if answer.text is None:
        return NO_ANSWER
    lines = [answer.text.strip()]
    if answer.citations:
        lines += ["", "Sources:"]
        for citation in answer.citations:
            metadata = citation.source.chunk.metadata
            where = (f", page {metadata['page']}" if metadata.get("page") else
                     f", {metadata['section']}" if metadata.get("section") else "")
            name = names.get(citation.source.file_key) or "a document"
            lines.append(f"[{citation.number}] {name}{where}")
    return "\n".join(lines)


def _command(text: str) -> str | None:
    """``/new`` for "/new", "/new@acme_bot" or "/NEW please"; None when it is no command."""
    if not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0].split("@", 1)[0].lower()


class BotService:

    def __init__(self, uow: UnitOfWork, platforms: Mapping[str, ChatPlatform],
                 app_url: str = "http://localhost:3000", chat_limit: int = 0):
        """``chat_limit``: the most messages a chat may send a bot in a minute (0: any)."""
        self.uow = uow
        self.platforms = platforms
        self.app_url = app_url
        self.chat_limit = chat_limit

    async def webhook_url(self, bot: Bot) -> str:
        """Where the chat app sends the bot's messages, with their secret: on this server's
        address, never a workspace's domain, which may pass to someone else."""
        return f"{self.app_url}/api/v1/bots/{bot.id}/webhook"

    async def create(self, project_name: str, kind: str, name: str,
                     credentials: Mapping[str, Any], tags: Sequence[str] = ()) -> Bot:
        """A new bot, once its chat app accepts the credentials (and, for Telegram, sends
        its messages here)."""
        project = await self._project(project_name)
        cleaned = clean_credentials(kind, credentials)
        platform = self.platforms[kind]
        account = await platform.check(cleaned)
        bot = await self.uow.bots.create(
            bot_id=BOT_PREFIX + secrets.token_urlsafe(16), project_id=project.id, kind=kind,
            name=name.strip(), account=account, credentials=cleaned,
            webhook_secret=secrets.token_urlsafe(32), tags=clean_tags(tags))
        await platform.register(cleaned, await self.webhook_url(bot), bot.webhook_secret)
        await record(self.uow, project.tenant_id, "bot.created", bot.id, project=project.name,
                     kind=kind, name=bot.name, account=account, tags=list(bot.tags))
        await self.uow.commit()
        return bot

    async def bots(self, project_name: str) -> list[Bot]:
        return await self.uow.bots.list_for_project((await self._project(project_name)).id)

    async def get(self, project_name: str, bot_id: str) -> Bot:
        project = await self._project(project_name)
        bot = await self.uow.bots.get(bot_id)
        if bot is None or bot.project_id != project.id:
            raise BotNotFound()
        return bot

    async def update(self, project_name: str, bot_id: str, changes: Mapping[str, Any]) -> Bot:
        """Change the fields given: ``name``, ``tags``, ``enabled`` or ``credentials``.

        New credentials are checked with the chat app first, and replace the old
        ones whole.
        """
        bot = await self.get(project_name, bot_id)
        values = dict(changes)
        if "name" in values:
            values["name"] = str(values["name"]).strip()
        if "tags" in values:
            values["tags"] = list(clean_tags(values["tags"] or ()))
        platform = self.platforms[bot.kind]
        if "credentials" in values:
            values["credentials"] = clean_credentials(bot.kind, values["credentials"])
            values["account"] = await platform.check(values["credentials"])
        updated = await self.uow.bots.update(bot.project_id, bot.id, values)
        assert updated is not None
        if "credentials" in values:
            await platform.register(updated.credentials, await self.webhook_url(updated),
                                    updated.webhook_secret)
        details = {k: v for k, v in values.items() if k != "credentials"}
        if "credentials" in values:
            details["credentials"] = "replaced"
        await record(self.uow, bot.tenant_id, "bot.updated", bot.id, project=bot.project_name,
                     **details)
        await self.uow.commit()
        return updated

    async def delete(self, project_name: str, bot_id: str) -> None:
        """The bot stops answering; its conversations stay with the project."""
        bot = await self.get(project_name, bot_id)
        try:
            await self.platforms[bot.kind].unregister(bot.credentials)
        except AppError as exc:
            # The token may be revoked already; the bot goes either way.
            logger.warning("Bot %s: could not stop its webhook: %s", bot.id, exc)
        await self.uow.bots.delete(bot.project_id, bot.id)
        await record(self.uow, bot.tenant_id, "bot.deleted", bot.id, project=bot.project_name,
                     kind=bot.kind, name=bot.name)
        await self.uow.commit()

    async def respond(self, bot: Bot, message: IncomingMessage,
                      answers: Callable[[], AnswerService], limits: LimitService) -> None:
        """Answer a message in its chat, once, however often the app delivers it.

        Commands: /start says what the bot does, /new starts a new conversation.
        ``answers`` makes the AnswerService, only for a question (commands need no
        model). A failure is answered with a short apology, and noted on the bot.
        """
        if not await self.uow.bots.first_delivery(bot.id, message.update_id, message.chat_key):
            return
        await self.uow.commit()
        command = _command(message.text.strip())
        error: str | None = None
        sent = (await self.uow.bots.recent_messages(bot.id, message.chat_key, 60)
                if self.chat_limit else 0)
        if sent > self.chat_limit + 1:
            return  # Told to slow down already: no reply costs anything.
        if sent == self.chat_limit + 1:
            reply = SLOW_DOWN
        elif command == "/start":
            reply = welcome(bot)
        elif command in ("/new", "/reset"):
            await self.uow.bots.set_chat_conversation(bot.id, message.chat_key, None)
            reply = NEW_CONVERSATION
        elif not message.text.strip():
            return
        else:
            try:
                reply = await self._answer(bot, message, answers, limits)
            except (RateLimited, AnswerQuotaExceeded, BudgetExceeded) as exc:
                reply, error = LIMIT_REACHED, exc.signal.value
            except AppError as exc:
                logger.error("Bot %s: answering failed: %s", bot.id, exc,
                             exc_info=exc.__cause__ or exc)
                reply, error = FAILED, exc.signal.value
        try:
            await self.platforms[bot.kind].send(bot.credentials, message.reply_to, reply)
        except AppError as exc:
            logger.warning("Bot %s: sending the reply failed: %s", bot.id, exc)
            error = f"Sending the reply failed: {exc}"
        await self.uow.bots.answered(bot.id, error)
        await self.uow.commit()

    async def _answer(self, bot: Bot, message: IncomingMessage,
                      answers: Callable[[], AnswerService], limits: LimitService) -> str:
        await limits.count_request(bot.tenant_id)
        await limits.check_answers(bot.tenant_id)
        conversation_id = await self.uow.bots.chat_conversation(bot.id, message.chat_key)
        if conversation_id is None:
            conversation = await self.uow.conversations.create(bot.project_id, None)
            conversation_id = conversation.id
            await self.uow.bots.set_chat_conversation(bot.id, message.chat_key, conversation_id)
            await self.uow.commit()
        filters = SearchFilters(tags=bot.tags) if bot.tags else None
        answer = await answers().ask(bot.project_name, message.text.strip(), top_k=TOP_K,
                                   conversation_id=conversation_id, filters=filters)
        names: dict[str, str | None] = {}
        for citation in answer.citations:
            key = citation.source.file_key
            if key not in names:
                found = await self.uow.files.get_by_key(bot.project_id, key)
                names[key] = found.original_name if found else None
        return reply_text(answer, names)

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project

