from ragolex.core.config import Settings

from .http_sender import HTTPWebhookSender


def create_webhook_sender(settings: Settings) -> HTTPWebhookSender:
    return HTTPWebhookSender(allow_private=settings.WEBHOOK_ALLOW_PRIVATE_URLS,
                             timeout_seconds=settings.WEBHOOK_TIMEOUT_SECONDS)
