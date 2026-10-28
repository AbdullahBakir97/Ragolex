from ragolex.core.config import Settings
from ragolex.domain.chat_platform import ChatPlatform

from .slack import SlackPlatform
from .telegram import TelegramPlatform
from .whatsapp import WhatsAppPlatform


def create_chat_platforms(settings: Settings) -> dict[str, ChatPlatform]:
    """A client for each chat app bots answer in, by the bots' kind."""
    timeout = settings.BOT_TIMEOUT_SECONDS
    return {"telegram": TelegramPlatform(timeout_seconds=timeout),
            "slack": SlackPlatform(timeout_seconds=timeout),
            "whatsapp": WhatsAppPlatform(timeout_seconds=timeout)}
