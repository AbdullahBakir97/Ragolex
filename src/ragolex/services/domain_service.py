"""Workspaces' own domains: added, proven by a TXT record, and then served on.

A workspace adds a domain such as help.acme.com and puts a TXT record with
a random token at _ragolex.help.acme.com. Once a check finds it, requests
that arrive with that host act for the workspace (see the API's
dependencies). Several workspaces may claim a domain, so a claim blocks
nobody; only one can prove it.
"""

import re
import secrets
from urllib.parse import urlsplit

from ragolex.core.errors import (
    DomainExists,
    DomainInvalid,
    DomainNotFound,
    DomainNotVerified,
    DomainTaken,
)
from ragolex.domain.dns import TxtResolver
from ragolex.domain.models import TenantDomain
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record

RECORD_PREFIX = "_ragolex."
VALUE_PREFIX = "ragolex-verification="
# More is unlikely to be a brand's, and each is looked up on its own.
MAX_DOMAINS = 20
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def record_name(domain: str) -> str:
    """Where the TXT record that proves the domain goes."""
    return RECORD_PREFIX + domain


def record_value(token: str) -> str:
    return VALUE_PREFIX + token


def host_name(host: str | None) -> str | None:
    """A request's Host header without its port, in lower case."""
    if not host:
        return None
    return (urlsplit("//" + host).hostname or "").rstrip(".") or None


def normalise_domain(value: str) -> str:
    """The domain in lower case and ASCII (international names as punycode).

    Raises DomainInvalid for anything but a host name of two or more labels.
    """
    name = value.strip().lower().rstrip(".")
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainInvalid() from exc
    labels = name.split(".")
    if (len(name) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels)
            or labels[-1].isdigit()):
        raise DomainInvalid()
    return name


class DomainService:

    def __init__(self, uow: UnitOfWork, resolver: TxtResolver | None = None,
                 app_url: str = "http://localhost:3000"):
        self.uow = uow
        self.resolver = resolver
        # The server's own host, which no workspace can claim.
        self.own_host = host_name(urlsplit(app_url).netloc)

    async def domains(self, tenant_id: int) -> list[TenantDomain]:
        return await self.uow.domains.list_for_tenant(tenant_id)

    async def add(self, tenant_id: int, domain: str, *, verified: bool = False) -> TenantDomain:
        """A new domain for the tenant, unverified unless ``verified`` (operators only)."""
        name = normalise_domain(domain)
        if name == self.own_host:
            raise DomainInvalid("The server's own domain serves every workspace")
        if len(await self.uow.domains.list_for_tenant(tenant_id)) >= MAX_DOMAINS:
            raise DomainInvalid(f"A workspace has at most {MAX_DOMAINS} domains")
        added = await self.uow.domains.add(tenant_id=tenant_id, domain=name,
                                           token=secrets.token_urlsafe(24))
        if added is None:
            raise DomainExists()
        await record(self.uow, tenant_id, "domain.added", name)
        if verified:
            await self._verified(added)
        await self.uow.commit()
        return await self._get(tenant_id, added.id)

    async def verify(self, tenant_id: int, domain_id: str) -> TenantDomain:
        """Look for the domain's TXT record; raises DomainNotVerified when it is not there."""
        domain = await self._get(tenant_id, domain_id)
        if domain.verified_at is not None:
            return domain
        assert self.resolver is not None, "verifying needs a TXT resolver"
        found = await self.resolver.txt(record_name(domain.domain))
        if record_value(domain.token) not in (value.strip() for value in found):
            await self.uow.domains.checked(domain.id, verified=False)
            await self.uow.commit()
            raise DomainNotVerified()
        await self._verified(domain)
        await self.uow.commit()
        return await self._get(tenant_id, domain_id)

    async def _verified(self, domain: TenantDomain) -> None:
        if not await self.uow.domains.checked(domain.id, verified=True):
            await self.uow.commit()  # Keep when it was checked.
            raise DomainTaken()
        await record(self.uow, domain.tenant_id, "domain.verified", domain.domain)

    async def remove(self, tenant_id: int, domain_id: str) -> None:
        """The domain stops serving the workspace at once."""
        domain = await self._get(tenant_id, domain_id)
        await self.uow.domains.delete(tenant_id, domain_id)
        await record(self.uow, tenant_id, "domain.removed", domain.domain)
        await self.uow.commit()

    async def _get(self, tenant_id: int, domain_id: str) -> TenantDomain:
        domain = await self.uow.domains.get(tenant_id, domain_id)
        if domain is None:
            raise DomainNotFound()
        return domain

    async def site(self, host: str | None) -> TenantDomain | None:
        """The verified domain a request's Host header names, if it is a workspace's."""
        name = host_name(host)
        if name is None or name == self.own_host or "." not in name:
            return None
        return await self.uow.domains.find_verified(name)

    async def base_url(self, tenant_id: int) -> str | None:
        """Where the workspace's web app is, on its own domain; None when it has none."""
        verified = [d for d in await self.uow.domains.list_for_tenant(tenant_id) if d.verified_at]
        return f"https://{verified[0].domain}" if verified else None
