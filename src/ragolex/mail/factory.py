from ragolex.core.config import Settings

from .smtp import SmtpMailer


def create_mailer(settings: Settings) -> SmtpMailer | None:
    """The mailer, when SMTP_HOST is set; no email is sent otherwise."""
    if not settings.SMTP_HOST:
        return None
    return SmtpMailer(host=settings.SMTP_HOST, port=settings.SMTP_PORT,
                      sender=settings.SMTP_FROM, security=settings.SMTP_SECURITY,
                      username=settings.SMTP_USERNAME, password=settings.SMTP_PASSWORD,
                      timeout_seconds=settings.SMTP_TIMEOUT_SECONDS)
