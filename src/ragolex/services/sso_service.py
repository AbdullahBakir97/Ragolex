import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from ragolex.core.errors import (
    DomainInvalid,
    OwnerRequired,
    SsoEmailNotAllowed,
    SsoFailed,
    SsoNeedsDomain,
    SsoNotConfigured,
    SsoRequestInvalid,
    SsoSecretRequired,
)
from ragolex.core.passwords import hash_password
from ragolex.domain.models import SsoProvider, SsoRequest, Tenant
from ragolex.domain.oidc import OidcClient
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.account_service import AccountService, SignedIn, normalise_email
from ragolex.services.audit import record
from ragolex.services.connection_service import code_challenge
from ragolex.services.domain_service import normalise_domain

CALLBACK_PATH = "/api/v1/auth/sso/callback"
# How long someone has to sign in at their identity provider and come back.
REQUEST_LIFETIME = timedelta(minutes=10)
ROLES = ("admin", "editor", "viewer")
SCOPES = "openid email profile"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _domain(email: str) -> str:
    """The email's domain, normalised; empty for an address that has none."""
    if "@" not in email:
        return ""
    try:
        return normalise_domain(email.rpartition("@")[2])
    except DomainInvalid:
        return ""


@dataclass(frozen=True)
class SsoStarted:
    """Where to send the person to sign in, and the key their browser keeps to finish it."""

    authorize_url: str
    browser_key: str


class SsoService:
    """Single sign-on with a workspace's OpenID Connect identity provider.

    The provider vouches for an email; a workspace can sign in only emails on
    its verified domains (proven with a TXT record, like the domains it is
    served on), so it cannot sign in as anyone else's account. A first
    sign-in makes the account, or adds an existing one to the workspace, with
    the provider's default role.
    """

    def __init__(self, uow: UnitOfWork, client: OidcClient, *, app_url: str,
                 session_days: int = 30):
        self.uow = uow
        self.client = client
        self.app_url = app_url.rstrip("/")
        self.session_days = session_days

    @property
    def redirect_uri(self) -> str:
        """Where identity providers send people back: register it with the app there."""
        return f"{self.app_url}{CALLBACK_PATH}"

    async def provider(self, tenant_id: int) -> SsoProvider | None:
        return await self.uow.sso.get(tenant_id)

    async def email_domains(self, tenant_id: int) -> list[str]:
        """The domains whose emails the workspace's provider may sign in: its verified ones."""
        return sorted(d.domain for d in await self.uow.domains.list_for_tenant(tenant_id)
                      if d.verified_at is not None)

    async def configure(self, tenant_id: int, *, issuer: str, client_id: str,
                        client_secret: str | None, default_role: str, enabled: bool,
                        required: bool = False, role: str | None = None) -> SsoProvider:
        """Set the workspace's provider, once its discovery document checks out. Without
        ``client_secret``, the one it has is kept.

        Only an owner (``role``) requires it or stops requiring it: owners keep their
        passwords, so whoever turns it on cannot lock themselves out. It needs a verified
        domain, or only owners could sign in.
        """
        issuer = issuer.strip().rstrip("/")
        current = await self.uow.sso.get(tenant_id)
        if required != (current.required if current else False) and role != "owner":
            raise OwnerRequired("Only an owner may require single sign-on, or stop requiring it")
        if required and enabled and not await self.email_domains(tenant_id):
            raise SsoNeedsDomain()
        await self.client.discover(issuer)
        if client_secret is None:
            if current is None:
                raise SsoSecretRequired()
            client_secret = current.client_secret
        provider = await self.uow.sso.save(
            tenant_id=tenant_id, issuer=issuer, client_id=client_id.strip(),
            client_secret=client_secret, default_role=default_role, enabled=enabled,
            required=required)
        await record(self.uow, tenant_id, "sso.configured", issuer, client_id=provider.client_id,
                     default_role=default_role, enabled=enabled, required=required)
        await self.uow.commit()
        return provider

    async def remove(self, tenant_id: int) -> None:
        provider = await self.uow.sso.get(tenant_id)
        if provider is None:
            raise SsoNotConfigured()
        await self.uow.sso.delete(tenant_id)
        await record(self.uow, tenant_id, "sso.removed", provider.issuer)
        await self.uow.commit()

    async def workspace_for(self, email: str) -> Tenant:
        """The workspace that signs this email in: the one that verified its domain and has
        single sign-on turned on."""
        domain = _domain(email)
        verified = await self.uow.domains.find_verified(domain) if domain else None
        provider = await self.uow.sso.get(verified.tenant_id) if verified else None
        tenant = await self.uow.tenants.get_by_id(verified.tenant_id) if verified else None
        if provider is None or not provider.enabled or tenant is None:
            raise SsoNotConfigured()
        return tenant

    async def start(self, tenant_id: int, return_to: str) -> SsoStarted:
        """Where to send the person to sign in; they come back to ``return_to``, a page of the
        web app on this server or one of the workspace's domains (its home page otherwise)."""
        provider = await self.uow.sso.get(tenant_id)
        if provider is None or not provider.enabled:
            raise SsoNotConfigured()
        metadata = await self.client.discover(provider.issuer)
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, browser_key = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        await self.uow.sso.add_request(SsoRequest(
            state_hash=_hash(state), tenant_id=tenant_id, nonce=nonce, code_verifier=verifier,
            next_url=await self._return_to(tenant_id, return_to),
            browser_hash=_hash(browser_key), expires_at=datetime.now(UTC) + REQUEST_LIFETIME))
        await self.uow.commit()
        query = urlencode({"response_type": "code", "client_id": provider.client_id,
                           "redirect_uri": self.redirect_uri, "scope": SCOPES, "state": state,
                           "nonce": nonce, "code_challenge": code_challenge(verifier),
                           "code_challenge_method": "S256"})
        joiner = "&" if "?" in metadata.authorization_endpoint else "?"
        return SsoStarted(f"{metadata.authorization_endpoint}{joiner}{query}", browser_key)

    async def find(self, state: str) -> SsoRequest:
        """The sign-in the provider sent someone back from, still to be finished."""
        request = await self.uow.sso.find_request(_hash(state)) if state else None
        if request is None:
            raise SsoRequestInvalid()
        return request

    async def finish(self, state: str, browser_key: str | None, code: str | None,
                     error: str | None = None) -> tuple[SignedIn, SsoRequest]:
        """Sign in the person the provider vouches for, in the workspace, from the browser that
        started it; finished once."""
        request = await self.uow.sso.take_request(_hash(state)) if state else None
        await self.uow.commit()
        if request is None or not browser_key or not secrets.compare_digest(
                request.browser_hash, _hash(browser_key)):
            raise SsoRequestInvalid()
        if error or not code:
            raise SsoFailed(f"the identity provider did not sign you in ({error or 'no code'})")
        provider = await self.uow.sso.get(request.tenant_id)
        if provider is None or not provider.enabled:
            raise SsoNotConfigured()
        metadata = await self.client.discover(provider.issuer)
        token = await self.client.exchange(
            metadata, client_id=provider.client_id, client_secret=provider.client_secret,
            code=code, redirect_uri=self.redirect_uri, code_verifier=request.code_verifier)
        claims = await self.client.verify(metadata, token, client_id=provider.client_id,
                                          nonce=request.nonce)
        email = await self._email(request.tenant_id, claims)
        signed_in = await self._sign_in(request.tenant_id, provider, email,
                                        str(claims.get("name") or "").strip())
        return signed_in, request

    async def _email(self, tenant_id: int, claims: dict) -> str:
        if claims.get("email_verified") is False:
            raise SsoEmailNotAllowed("the identity provider has not verified this email")
        email = claims.get("email")
        if not email:
            # Entra ID may give only the sign-in name, which is the email there.
            name = str(claims.get("preferred_username") or "")
            email = name if "@" in name else None
        if not email:
            raise SsoEmailNotAllowed("the identity provider sent no email")
        email = normalise_email(str(email))
        if _domain(email) not in await self.email_domains(tenant_id):
            raise SsoEmailNotAllowed(f"{email} is not on one of the workspace's verified domains")
        return email

    async def _sign_in(self, tenant_id: int, provider: SsoProvider, email: str,
                       name: str) -> SignedIn:
        login = await self.uow.users.login(email)
        user = login.user if login else await self.uow.users.create(
            # An account made here signs in through the provider; a password reset can give it
            # a password of its own.
            email=email, name=name or email, password_hash=hash_password(secrets.token_urlsafe(32)))
        assert user is not None
        membership = await self.uow.memberships.get(user.id, tenant_id)
        if membership is None:
            membership = await self.uow.memberships.add(user_id=user.id, tenant_id=tenant_id,
                                                        role=provider.default_role)
            await record(self.uow, tenant_id, "member.added", email,
                         role=provider.default_role, via="sso")
        await self.uow.users.logged_in(user.id)
        return await AccountService(self.uow, self.session_days,
                                    app_url=self.app_url).start_session(user, membership)

    async def _return_to(self, tenant_id: int, return_to: str) -> str:
        fallback = f"{self.app_url}/"
        parts = urlsplit(return_to)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return fallback
        app = urlsplit(self.app_url)
        if (parts.scheme, parts.netloc) == (app.scheme, app.netloc):
            return return_to
        verified = {d.domain for d in await self.uow.domains.list_for_tenant(tenant_id)
                    if d.verified_at is not None}
        return return_to if parts.scheme == "https" and parts.netloc.lower() in verified \
            else fallback
