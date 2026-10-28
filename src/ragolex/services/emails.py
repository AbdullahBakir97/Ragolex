"""The emails accounts send, and sending them without failing the request."""

import logging

from ragolex.core.errors import MailFailed
from ragolex.domain.mailer import Mailer
from ragolex.domain.models import Invitation, Mail, User

logger = logging.getLogger(__name__)


def invitation_mail(invitation: Invitation, link: str, inviter: User | None) -> Mail:
    who = inviter.name if inviter else "An administrator"
    return Mail(
        to=invitation.email,
        subject=f"You are invited to {invitation.tenant_name} on Ragolex",
        text=f"Hello,\n\n"
             f'{who} invited you to the workspace "{invitation.tenant_name}" on Ragolex, '
             f"as {invitation.role}.\n\n"
             f"Accept the invitation here:\n{link}\n\n"
             f"The link works once, until {invitation.expires_at:%Y-%m-%d %H:%M} UTC. "
             f"If you did not expect this email, ignore it.\n")


def password_reset_mail(user: User, link: str) -> Mail:
    return Mail(
        to=user.email,
        subject="Reset your Ragolex password",
        text=f"Hello {user.name},\n\n"
             f"Someone asked to reset the password of your Ragolex account, {user.email}. "
             f"Choose a new one here:\n{link}\n\n"
             f"The link works once, for an hour. If you did not ask for it, ignore this "
             f"email: your password stays as it is.\n")


async def send_mail(mailer: Mailer, mail: Mail) -> None:
    """Send the email, and log it when that fails (after the response, nobody else hears)."""
    try:
        await mailer.send(mail)
    except MailFailed as exc:
        logger.warning("An email could not be sent: %s", exc)
