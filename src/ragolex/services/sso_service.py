import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from ragolex.core.errors import (
    DomainInvalid,
    OwnerRequired,
    SsoCertificateInvalid,
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
from ragolex.domain.saml import SamlServiceProvider, SamlVerifier
from ragolex.services.account_service import AccountService, SignedIn, normalise_email
from ragolex.services.audit import record
from ragolex.services.connection_service import code_challenge
from ragolex.services.domain_service import normalise_domain

CALLBACK_PATH = "/api/v1/auth/sso/callback"
SAML_PATH = "/api/v1/auth/sso/saml"
PROTOCOLS = ("oidc", "saml")
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
                 session_days: int = 30, saml: SamlVerifier | None = None,
                 allow_private_urls: bool = False):
        self.uow = uow
        self.client = client
        self.saml = saml
        self.app_url = app_url.rstrip("/")
        self.session_days = session_days
        self.allow_private_urls = allow_private_urls

    @property
    def service_provider(self) -> SamlServiceProvider:
        """This server to SAML identity providers: its entity ID is its metadata's address."""
        return SamlServiceProvider(entity_id=f"{self.app_url}{SAML_PATH}/metadata",
                                   acs_url=f"{self.app_url}{SAML_PATH}/acs")

    def _saml(self) -> SamlVerifier:
        if self.saml is None:
            raise SsoNotConfigured("SAML is not available on this server")
        return self.saml

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

    async def configure(self, tenant_id: int, *, issuer: str, default_role: str, enabled: bool,
                        protocol: str = "oidc", client_id: str | None = None,
                        client_secret: str | None = None, sso_url: str | None = None,
                        certificate: str | None = None, required: bool = False,
                        role: str | None = None) -> SsoProvider:
        """Set the workspace's provider.

        OpenID Connect: ``issuer``, ``client_id`` and ``client_secret``, once the
        discovery document checks out. SAML: ``issuer`` is the provider's entity
        ID, with ``sso_url`` and its signing ``certificate``. Left out, the secret
        or certificate it has is kept.

        Only an owner (``role``) requires it or stops requiring it: owners keep their
        passwords, so whoever turns it on cannot lock themselves out. It needs a verified
        domain, or only owners could sign in.
        """
        current = await self.uow.sso.get(tenant_id)
        if required != (current.required if current else False) and role != "owner":
            raise OwnerRequired("Only an owner may require single sign-on, or stop requiring it")
        if required and enabled and not await self.email_domains(tenant_id):
            raise SsoNeedsDomain()
        kept = current if current and current.protocol == protocol else None
        if protocol == "saml":
            issuer = issuer.strip()
            sso_url = self._check_sso_url((sso_url or "").strip())
            if certificate is not None:
                certificate, _ = self._saml().load_certificate(certificate)
            elif kept is not None:
                certificate = kept.certificate
            else:
                raise SsoCertificateInvalid("Give the identity provider's signing certificate")
            client_id, client_secret, details = "", "", {"sso_url": sso_url}
        else:
            issuer = issuer.strip().rstrip("/")
            await self.client.discover(issuer)
            if client_secret is None:
                if kept is None:
                    raise SsoSecretRequired()
                client_secret = kept.client_secret
            client_id = (client_id or "").strip()
            sso_url, certificate, details = None, None, {"client_id": client_id}
        provider = await self.uow.sso.save(
            tenant_id=tenant_id, issuer=issuer, client_id=client_id,
            client_secret=client_secret, default_role=default_role, enabled=enabled,
            required=required, protocol=protocol, sso_url=sso_url, certificate=certificate)
        await record(self.uow, tenant_id, "sso.configured", issuer, protocol=protocol, **details,
                     default_role=default_role, enabled=enabled, required=required)
        await self.uow.commit()
        return provider

    def _check_sso_url(self, url: str) -> str:
        parts = urlsplit(url)
        local = (parts.hostname or "") in ("localhost", "127.0.0.1", "::1")
        if not parts.netloc or (parts.scheme != "https" and not (
                parts.scheme == "http" and local and self.allow_private_urls)):
            raise SsoFailed("the identity provider's sign-in URL must be an https address")
        return url

    def certificate_expiry(self, provider: SsoProvider) -> datetime | None:
        if provider.protocol != "saml" or not provider.certificate or self.saml is None:
            return None
        return self.saml.load_certificate(provider.certificate)[1]

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
        next_url = await self._return_to(tenant_id, return_to)
        browser_key, now = secrets.token_urlsafe(32), datetime.now(UTC)
        if provider.protocol == "saml":
            assert provider.sso_url is not None
            # The AuthnRequest's ID, which the assertion answers: an XML name.
            state = f"_{secrets.token_hex(20)}"
            await self.uow.sso.add_request(SsoRequest(
                state_hash=_hash(state), tenant_id=tenant_id, nonce="", code_verifier="",
                next_url=next_url, browser_hash=_hash(browser_key),
                expires_at=now + REQUEST_LIFETIME))
            await self.uow.commit()
            return SsoStarted(self._saml().authn_request_url(
                self.service_provider, sso_url=provider.sso_url, request_id=state,
                relay_state=state, now=now), browser_key)
        metadata = await self.client.discover(provider.issuer)
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        await self.uow.sso.add_request(SsoRequest(
            state_hash=_hash(state), tenant_id=tenant_id, nonce=nonce, code_verifier=verifier,
            next_url=next_url, browser_hash=_hash(browser_key),
            expires_at=now + REQUEST_LIFETIME))
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

    async def take_saml_response(self, relay_state: str, saml_response: str) -> SsoRequest:
        """Check a SAML provider's response (POSTed by the browser) to a sign-in started here,
        and keep the email it vouches for on that sign-in, once.

        The browser's binding cookie does not come with another site's POST, so the
        browser that started it then finishes it at the callback, which checks that.
        """
        request = await self.uow.sso.find_request(_hash(relay_state)) if relay_state else None
        if request is None:
            raise SsoRequestInvalid()
        provider = await self.uow.sso.get(request.tenant_id)
        if (provider is None or not provider.enabled or provider.protocol != "saml"
                or not provider.certificate):
            raise SsoNotConfigured()
        assertion = self._saml().verify(
            self.service_provider, saml_response, idp_entity_id=provider.issuer,
            certificate=provider.certificate, now=datetime.now(UTC))
        if not secrets.compare_digest(assertion.in_response_to, relay_state):
            raise SsoFailed("the assertion answers another sign-in")
        email = await self._email(request.tenant_id, {"email": assertion.email})
        if len(email) > 254:
            raise SsoEmailNotAllowed("the identity provider sent an email that is too long")
        name = (assertion.name or "").strip()[:200] or None
        if not await self.uow.sso.vouch(_hash(relay_state), email=email, name=name):
            raise SsoRequestInvalid()  # Answered already: a replay.
        await self.uow.commit()
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
        provider = await self.uow.sso.get(request.tenant_id)
        if provider is None or not provider.enabled:
            raise SsoNotConfigured()
        if provider.protocol == "saml":
            if not request.vouched_email:
                raise SsoFailed("the identity provider did not sign you in")
            return await self._sign_in(request.tenant_id, provider, request.vouched_email,
                                       request.vouched_name or ""), request
        if error or not code:
            raise SsoFailed(f"the identity provider did not sign you in ({error or 'no code'})")
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
