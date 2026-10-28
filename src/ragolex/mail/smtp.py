import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from ragolex.core.errors import MailFailed
from ragolex.domain.models import Mail


class SmtpMailer:
    """Sends email through an SMTP server, one connection per email.

    smtplib blocks, so each email is sent in a worker thread. Certificates
    are checked with the system's trusted authorities.
    """

    def __init__(self, *, host: str, port: int, sender: str, security: str = "starttls",
                 username: str = "", password: str = "", timeout_seconds: float = 10.0):
        self.host = host
        self.port = port
        self.sender = sender
        self.security = security
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    async def send(self, mail: Mail) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message["Message-ID"] = make_msgid(domain=self.host)
        message.set_content(mail.text)
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        try:
            if self.security == "tls":
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout_seconds, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds)
            with server:
                if self.security == "starttls":
                    server.starttls(context=context)
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # The exception's type says enough; its text can quote the server.
            raise MailFailed(type(exc).__name__) from exc
