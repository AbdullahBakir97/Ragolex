import base64
import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ragolex.core.errors import (
    ConnectionDenied,
    ConnectionInUse,
    ConnectionNotFound,
    ConnectionRequestInvalid,
    ConnectionWrongKind,
    ConnectorNotConfigured,
    CrawlFailed,
)
from ragolex.domain.models import (
    CONNECTION_KINDS,
    Connection,
    ConnectionKind,
    ConnectionRequest,
)
from ragolex.domain.oauth import OAuthProvider
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record

CALLBACK_PATH = "/api/v1/connections/callback"
# How long someone has to sign in at the provider and come back.
REQUEST_LIFETIME = timedelta(minutes=15)
# Tokens are refreshed this long before they expire, so a sync does not outlive them.
REFRESH_BEFORE = timedelta(minutes=5)
NAMES = {"notion": "Notion", "google_drive": "Google Drive"}


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


@dataclass(frozen=True)
class Started:
    """Where to send the person to sign in, and the key their browser keeps to finish it."""

    authorize_url: str
    browser_key: str


def code_challenge(verifier: str) -> str:
    """PKCE's S256 challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def with_query(url: str, **params: str) -> str:
    """``url`` with ``params`` added to its query."""
    parts = urlsplit(url)
    query = [*parse_qsl(parts.query), *params.items()]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class ConnectionService:
    """A workspace's sign-ins to Notion and Google Drive, which its sources read through.

    Connecting sends an admin to the provider with a single-use state; the
    provider sends them back to the callback with a code, which is exchanged
    for tokens. Google's tokens last an hour and are refreshed before syncs.
    """

    def __init__(self, uow: UnitOfWork, providers: Mapping[str, OAuthProvider], *,
                 app_url: str = "", now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.uow = uow
        self.providers = providers
        self.app_url = app_url.rstrip("/")
        self.now = now

    @property
    def redirect_uri(self) -> str:
        """Where providers send people back: register it with the OAuth app."""
        return f"{self.app_url}{CALLBACK_PATH}"

    def available(self) -> list[ConnectionKind]:
        """The services the server has an OAuth app with."""
        return [kind for kind in CONNECTION_KINDS if kind in self.providers]

    async def start(self, tenant_id: int, kind: ConnectionKind, *, user_id: int | None,
                    return_to: str | None) -> Started:
        """Where to send the admin to sign in; they come back to ``return_to`` (a page of the
        web app on this server, or on one of the workspace's domains). Their browser keeps
        ``browser_key``, which finishing the sign-in needs."""
        provider = self.providers.get(kind)
        if provider is None:
            raise ConnectorNotConfigured()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        browser_key = secrets.token_urlsafe(32)
        await self.uow.connections.add_request(ConnectionRequest(
            state_hash=_hash(state), tenant_id=tenant_id, kind=kind, code_verifier=verifier,
            return_to=await self._return_to(tenant_id, return_to),
            expires_at=self.now() + REQUEST_LIFETIME, browser_hash=_hash(browser_key),
            user_id=user_id))
        await self.uow.commit()
        return Started(provider.authorize_url(state=state, redirect_uri=self.redirect_uri,
                                              code_challenge=code_challenge(verifier)),
                       browser_key)

    async def find(self, state: str) -> ConnectionRequest:
        """The sign-in the provider sent someone back from, still to be finished."""
        request = await self.uow.connections.find_request(_hash(state)) if state else None
        if request is None:
            raise ConnectionRequestInvalid()
        return request

    async def take(self, state: str, browser_key: str | None) -> ConnectionRequest:
        """The sign-in to finish, by the browser that started it; it is finished only once."""
        request = await self.uow.connections.take_request(_hash(state)) if state else None
        await self.uow.commit()
        if request is None or not browser_key or not secrets.compare_digest(
                request.browser_hash, _hash(browser_key)):
            raise ConnectionRequestInvalid()
        return request

    async def connect(self, request: ConnectionRequest, code: str | None,
                      error: str | None = None) -> Connection:
        """Exchange the provider's code for tokens, and keep them: as a new connection, or in
        the workspace's connection to the same account."""
        if error or not code:
            raise ConnectionDenied()
        provider = self.providers.get(request.kind)
        if provider is None:
            raise ConnectorNotConfigured()
        grant = await provider.exchange(code=code, redirect_uri=self.redirect_uri,
                                        code_verifier=request.code_verifier)
        # Signing in again with the same account renews that connection: its sources carry on.
        for existing in await self.uow.connections.list_for_tenant(request.tenant_id):
            if (existing.kind, existing.account) == (request.kind, grant.account):
                await self.uow.connections.set_tokens(existing.id, grant.tokens)
                await record(self.uow, request.tenant_id, "connection.renewed", existing.id,
                             kind=existing.kind, account=existing.account)
                await self.uow.commit()
                return await self.get(request.tenant_id, existing.id)
        connection = await self.uow.connections.create(
            connection_id=f"con_{secrets.token_urlsafe(16)}", tenant_id=request.tenant_id,
            kind=request.kind, account=grant.account, tokens=grant.tokens,
            created_by_user_id=request.user_id)
        await record(self.uow, request.tenant_id, "connection.created", connection.id,
                     kind=connection.kind, account=connection.account)
        await self.uow.commit()
        return connection

    async def connections(self, tenant_id: int) -> list[Connection]:
        return await self.uow.connections.list_for_tenant(tenant_id)

    async def get(self, tenant_id: int, connection_id: str,
                  kind: str | None = None) -> Connection:
        """The workspace's connection; of ``kind`` when given."""
        connection = await self.uow.connections.get(tenant_id, connection_id)
        if connection is None:
            raise ConnectionNotFound()
        if kind is not None and connection.kind != kind:
            raise ConnectionWrongKind(f"{connection_id} is a {NAMES[connection.kind]} "
                                      f"connection, not {NAMES.get(kind, kind)}")
        return connection

    async def delete(self, tenant_id: int, connection_id: str) -> None:
        """Forget the connection's tokens. Its sources must be removed first."""
        connection = await self.get(tenant_id, connection_id)
        if connection.sources_count:
            raise ConnectionInUse(f"{connection.sources_count} source(s) read through it")
        await self.uow.connections.delete(tenant_id, connection_id)
        await record(self.uow, tenant_id, "connection.deleted", connection_id,
                     kind=connection.kind, account=connection.account)
        await self.uow.commit()

    async def access_token(self, connection_id: str, kind: str) -> str:
        """A token to read with, refreshed first when it is about to expire.

        Raises CrawlFailed, for the source's status, when the connection is
        gone or the provider refuses to refresh it.
        """
        tokens = await self.uow.connections.tokens(connection_id)
        if tokens is None:
            raise CrawlFailed("the source's connection was removed")
        if not self._expiring(tokens.expires_at) or not tokens.refresh_token:
            return tokens.access_token
        # One sync refreshes at a time; another that waited uses its new token.
        tokens = await self.uow.connections.tokens(connection_id, lock=True)
        assert tokens is not None
        if not self._expiring(tokens.expires_at) or not tokens.refresh_token:
            await self.uow.commit()
            return tokens.access_token
        provider = self.providers.get(kind)
        if provider is None:
            await self.uow.commit()
            raise CrawlFailed(f"the server has no {NAMES.get(kind, kind)} app to refresh the "
                              "connection with")
        try:
            grant = await provider.refresh(tokens.refresh_token)
        except Exception as exc:
            reason = str(exc) or type(exc).__name__
            await self.uow.connections.failed(connection_id, reason)
            await self.uow.commit()
            raise CrawlFailed(f"{reason}; connect it again") from exc
        refreshed = grant.tokens
        if refreshed.refresh_token is None:
            refreshed = replace(refreshed, refresh_token=tokens.refresh_token)
        await self.uow.connections.set_tokens(connection_id, refreshed)
        await self.uow.commit()
        return refreshed.access_token

    def _expiring(self, expires_at: datetime | None) -> bool:
        return expires_at is not None and expires_at - REFRESH_BEFORE <= self.now()

    async def _return_to(self, tenant_id: int, return_to: str | None) -> str:
        """``return_to`` when it is on this server's web app or a verified domain of the
        workspace (never elsewhere); the Admin page otherwise."""
        fallback = f"{self.app_url}/admin"
        if not return_to:
            return fallback
        parts = urlsplit(return_to)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return fallback
        app = urlsplit(self.app_url)
        if (parts.scheme, parts.netloc) == (app.scheme, app.netloc):
            return return_to
        verified = {domain.domain for domain in await self.uow.domains.list_for_tenant(tenant_id)
                    if domain.verified_at is not None}
        if parts.scheme == "https" and parts.netloc.lower() in verified:
            return return_to
        return fallback
