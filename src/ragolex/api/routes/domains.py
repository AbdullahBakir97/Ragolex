"""A workspace's own domains, and what a request's domain says about the site.

Admins add a domain, put the TXT record it shows at their DNS provider and
ask for a check; once verified, the domain serves the workspace. The public
routes tell the web app which workspace a domain is, and tell a reverse
proxy such as Caddy which domains it may get certificates for.
"""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Response, status

from ragolex.api.dependencies import (
    ADMIN,
    DomainServiceDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    SiteDep,
)
from ragolex.api.schemas import (
    DnsRecord,
    DomainIdPath,
    DomainRequest,
    DomainResponse,
    SiteResponse,
    error_responses,
)
from ragolex.core.errors import (
    DnsLookupFailed,
    DomainExists,
    DomainInvalid,
    DomainNotFound,
    DomainNotVerified,
    DomainTaken,
)
from ragolex.domain.models import TenantDomain
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.domain_service import (
    host_name,
    normalise_domain,
    record_name,
    record_value,
)

router = APIRouter(prefix="/api/v1", tags=["domains"], dependencies=[ADMIN])
public_router = APIRouter(prefix="/api/v1", tags=["domains"])


def _domain(domain: TenantDomain, target: str) -> DomainResponse:
    return DomainResponse(
        id=domain.id, domain=domain.domain, verified=domain.verified_at is not None,
        created_at=domain.created_at, verified_at=domain.verified_at,
        checked_at=domain.checked_at,
        records=[DnsRecord(type="TXT", name=record_name(domain.domain),
                           value=record_value(domain.token)),
                 DnsRecord(type="CNAME", name=domain.domain, value=target)])


def _target(app_url: str) -> str:
    """The host a workspace's domain points at: the server's own."""
    return host_name(urlsplit(app_url).netloc) or "localhost"


@router.get("/domains", summary="The workspace's own domains, by name")
async def list_domains(principal: PrincipalDep, service: DomainServiceDep,
                       settings: SettingsDep) -> list[DomainResponse]:
    return [_domain(domain, _target(settings.APP_URL))
            for domain in await service.domains(principal.tenant_id)]


@router.post("/domains", status_code=status.HTTP_201_CREATED,
             summary="Add a domain for the workspace to serve on",
             description="It serves nothing until verified: add the TXT record it returns at "
                         "the domain's DNS provider, then `POST …/verify`. Point the domain at "
                         "this server with the CNAME (or an A record).",
             responses=error_responses(DomainInvalid, DomainExists))
async def add_domain(request: DomainRequest, principal: PrincipalDep, service: DomainServiceDep,
                     settings: SettingsDep) -> DomainResponse:
    return _domain(await service.add(principal.tenant_id, request.domain),
                   _target(settings.APP_URL))


@router.post("/domains/{domain_id}/verify", summary="Check the domain's TXT record",
             description="Looks the record up now, without caching. Once found, the domain "
                         "serves the workspace: requests to it act for it, and invitation "
                         "links use it.",
             responses=error_responses(DomainNotFound, DomainNotVerified, DomainTaken,
                                       DnsLookupFailed))
async def verify_domain(domain_id: DomainIdPath, principal: PrincipalDep,
                        service: DomainServiceDep, settings: SettingsDep) -> DomainResponse:
    return _domain(await service.verify(principal.tenant_id, str(domain_id)),
                   _target(settings.APP_URL))


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a domain", description="It stops serving the workspace at once.",
               responses=error_responses(DomainNotFound))
async def remove_domain(domain_id: DomainIdPath, principal: PrincipalDep,
                        service: DomainServiceDep) -> Response:
    await service.remove(principal.tenant_id, str(domain_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.get("/domains/allowed", summary="Whether a domain is a verified workspace's",
                   description="For a reverse proxy's on-demand certificates, such as Caddy's "
                               "`on_demand_tls` `ask`: `200` for a verified domain, `404` "
                               "otherwise. Needs no key.",
                   responses=error_responses(DomainNotFound))
async def domain_allowed(domain: Annotated[str, Query(max_length=253)],
                         session: SessionDep) -> dict[str, str]:
    try:
        name = normalise_domain(domain)
    except DomainInvalid as exc:
        raise DomainNotFound() from exc
    if await SqlUnitOfWork(session).domains.find_verified(name) is None:
        raise DomainNotFound()
    return {"domain": name}


@public_router.get("/site", summary="What this domain serves, for the web app before sign-in",
                   description="The workspace whose own domain the request came to, and "
                               "whether people sign in and may sign up here. Needs no key.")
async def site(site: SiteDep, settings: SettingsDep) -> SiteResponse:
    return SiteResponse(workspace=site.tenant_name if site else None,
                        accounts_enabled=settings.AUTH_ENABLED,
                        signup_enabled=settings.AUTH_ENABLED and settings.SIGNUP_ENABLED
                        and site is None)
