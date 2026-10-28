"""Single sign-on: a workspace's OpenID Connect identity provider, and signing in through it.

Admins set the provider. People find their workspace by their email's
domain, are sent to the provider, and come back to the callback, which
signs them in (making their account, or adding it to the workspace, the
first time) and returns them to the web app.
"""

import logging
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from ragolex.api.dependencies import (
    ACCOUNTS_ON,
    ADMIN,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    SiteDep,
    SsoServiceDep,
    get_oidc_client,
)
from ragolex.api.routes.accounts import _set_cookie
from ragolex.api.schemas import (
    SsoDiscoverRequest,
    SsoDiscoverResponse,
    SsoProviderResponse,
    SsoSettingsRequest,
    SsoSettingsResponse,
    error_responses,
)
from ragolex.core.errors import (
    AppError,
    OwnerRequired,
    SsoFailed,
    SsoNeedsDomain,
    SsoNotConfigured,
    SsoRequestInvalid,
    SsoSecretRequired,
)
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.connection_service import with_query
from ragolex.services.sso_service import CALLBACK_PATH, SsoService

logger = logging.getLogger(__name__)

# Holds the key of a sign-in in progress, for the browser that started it to finish it.
BROWSER_COOKIE = "ragolex_sso"
COOKIE_PATH = "/api/v1/auth/sso"

router = APIRouter(prefix="/api/v1/sso", tags=["single sign-on"], dependencies=[ADMIN])
public_router = APIRouter(prefix="/api/v1/auth/sso", tags=["single sign-on"],
                          dependencies=[ACCOUNTS_ON])


async def _settings(service: SsoService, tenant_id: int) -> SsoSettingsResponse:
    provider = await service.provider(tenant_id)
    return SsoSettingsResponse(
        provider=SsoProviderResponse(
            issuer=provider.issuer, client_id=provider.client_id,
            default_role=provider.default_role,  # type: ignore[arg-type]
            enabled=provider.enabled, required=provider.required,
            created_at=provider.created_at,
            updated_at=provider.updated_at) if provider else None,
        redirect_uri=service.redirect_uri, email_domains=await service.email_domains(tenant_id))


@router.get("", summary="The workspace's single sign-on")
async def get_sso(principal: PrincipalDep, service: SsoServiceDep) -> SsoSettingsResponse:
    return await _settings(service, principal.tenant_id)


@router.put("", summary="Set the workspace's OpenID Connect identity provider",
            description="Its discovery document is read first, so a wrong issuer is refused.",
            responses=error_responses(SsoFailed, SsoSecretRequired, OwnerRequired,
                                      SsoNeedsDomain))
async def set_sso(body: SsoSettingsRequest, principal: PrincipalDep,
                  service: SsoServiceDep) -> SsoSettingsResponse:
    await service.configure(principal.tenant_id, issuer=body.issuer, client_id=body.client_id,
                            client_secret=body.client_secret, default_role=body.default_role,
                            enabled=body.enabled, required=body.required, role=principal.role)
    return await _settings(service, principal.tenant_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove the workspace's single sign-on",
               description="Accounts made by it stay, and can set a password with a reset link.",
               responses=error_responses(SsoNotConfigured))
async def delete_sso(principal: PrincipalDep, service: SsoServiceDep) -> Response:
    await service.remove(principal.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _service(request: Request, session: SessionDep, settings: SettingsDep) -> SsoService:
    """The service outside a signed-in request: the sign-in itself, or the provider's redirect."""
    return SsoService(SqlUnitOfWork(session), get_oidc_client(request), app_url=settings.APP_URL,
                      session_days=settings.SESSION_DAYS)


@public_router.post("/discover", summary="Which workspace signs this email in",
                    description="The workspace that verified the email's domain and has single "
                                "sign-on turned on.",
                    responses=error_responses(SsoNotConfigured))
async def discover(body: SsoDiscoverRequest, request: Request, session: SessionDep,
                   settings: SettingsDep) -> SsoDiscoverResponse:
    tenant = await _service(request, session, settings).workspace_for(body.email)
    return SsoDiscoverResponse(workspace=tenant.name,
                               start_url=f"{COOKIE_PATH}/start?workspace={quote(tenant.name)}")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


# The next two are for browsers, not API clients, so they are not in the schema.
@public_router.get("/start", include_in_schema=False)
async def start(request: Request, session: SessionDep, settings: SettingsDep, site: SiteDep,
                workspace: Annotated[str, Query(max_length=64)] = "",
                next: Annotated[str, Query(max_length=2000)] = "/") -> Response:
    service = _service(request, session, settings)
    here = str(request.base_url).rstrip("/")
    path = next if next.startswith("/") and not next.startswith("//") else "/"
    try:
        tenant_id = site.tenant_id if site else None
        if tenant_id is None:
            tenant = await service.uow.tenants.get_by_name(workspace)
            if tenant is None:
                raise SsoNotConfigured()
            tenant_id = tenant.id
        started = await service.start(tenant_id, f"{here}{path}")
    except AppError as exc:
        return RedirectResponse(with_query(f"{here}/signin", sso_error=exc.signal.value),
                                status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(started.authorize_url, status_code=status.HTTP_303_SEE_OTHER)
    # Lax, unlike the session cookie: the provider's redirect back is another site's link.
    response.set_cookie(BROWSER_COOKIE, started.browser_key, max_age=10 * 60, path=COOKIE_PATH,
                        httponly=True, samesite="lax", secure=settings.SESSION_COOKIE_SECURE)
    return response


@public_router.get("/callback", include_in_schema=False)
async def callback(request: Request, session: SessionDep, settings: SettingsDep,
                   state: Annotated[str, Query(max_length=200)] = "",
                   code: Annotated[str | None, Query(max_length=4000)] = None,
                   error: Annotated[str | None, Query(max_length=200)] = None) -> Response:
    service = _service(request, session, settings)
    try:
        pending = await service.find(state)
    except SsoRequestInvalid as exc:
        return _back(f"{service.app_url}/signin", sso_error=exc.signal.value)
    # Started on one of the workspace's domains: its cookie is there, so finish there.
    started_on = urlsplit(pending.next_url)
    if started_on.netloc.lower() != request.url.netloc.lower():
        return RedirectResponse(f"{_origin(pending.next_url)}{CALLBACK_PATH}?{request.url.query}",
                                status_code=status.HTTP_303_SEE_OTHER)
    try:
        signed_in, finished = await service.finish(state, request.cookies.get(BROWSER_COOKIE),
                                                   code, error)
    except AppError as exc:
        logger.info("A single sign-on failed: %s", exc)
        return _back(f"{_origin(pending.next_url)}/signin", sso_error=exc.signal.value)
    response = _back(finished.next_url)
    _set_cookie(response, signed_in, settings)
    return response


def _back(url: str, **params: str) -> RedirectResponse:
    response = RedirectResponse(with_query(url, **params) if params else url,
                                status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(BROWSER_COOKIE, path=COOKIE_PATH)
    return response
