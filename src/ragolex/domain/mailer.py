"""The interface emails are sent through. The SMTP one is in ragolex.mail."""

from typing import Protocol

from .models import Mail


class Mailer(Protocol):

    async def send(self, mail: Mail) -> None:
        """Send the email; raises MailFailed when the server did not take it."""
        ...
