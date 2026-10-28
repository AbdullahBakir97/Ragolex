from typing import Protocol

from .models import OAuthGrant


class OAuthProvider(Protocol):
    """Signs a workspace in to Notion or Google Drive with OAuth 2.0, and keeps it signed in.

    Raises ConnectionFailed when the provider refuses a code or a refresh
    token, or cannot be reached.
    """

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        """Where to send people to sign in and allow reading; they come back to
        ``redirect_uri`` with ``state`` and a code."""
        ...

    async def exchange(self, *, code: str, redirect_uri: str,
                       code_verifier: str) -> OAuthGrant:
        """The tokens and account for the code the provider sent people back with."""
        ...

    async def refresh(self, refresh_token: str) -> OAuthGrant:
        """New tokens, before the old ones expire."""
        ...

    async def aclose(self) -> None: ...
