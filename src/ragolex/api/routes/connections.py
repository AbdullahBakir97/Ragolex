"""A workspace's connections to Notion and Google Drive, which its sources read through.

An admin starts a connection and is sent to the service to sign in and pick
what may be read; the service sends them back to the callback, which keeps
the tokens and returns them to the web app.
"""

import logging
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from ragolex.api.dependencies import (
    ADMIN,
    ConnectionServiceDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    get_oauth_providers,
)
from ragolex.api.schemas import (
    ConnectionIdPath,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionStartRequest,
    ConnectionStartResponse,
    error_responses,
)
from ragolex.core import log_context
from ragolex.core.errors import (
    AppError,
    ConnectionInUse,
    ConnectionNotFound,
    ConnectionRequestInvalid,
    ConnectorNotConfigured,
)
from ragolex.domain.models import Connection
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.connection_service import (
    CALLBACK_PATH,
    ConnectionService,
    with_query,
)

logger = logging.getLogger(__name__)

# Holds the key of a sign-in in progress, for the browser that started it to finish it.
BROWSER_COOKIE = "ragolex_connect"

router = APIRouter(prefix="/api/v1/connections", tags=["connections"])
public_router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


def _connection(connection: Connection) -> ConnectionResponse:
    return ConnectionResponse(id=connection.id, kind=connection.kind, account=connection.account,
                              created_by=connection.created_by,
                              sources_count=connection.sources_count,
                              created_at=connection.created_at,
                              last_error=connection.last_error,
                              last_error_at=connection.last_error_at)


@router.get("", dependencies=[ADMIN], summary="The workspace's connections, oldest first",
            description="With the services this server can connect, and the redirect URI to "
                        "register with their OAuth apps.")
async def list_connections(principal: PrincipalDep,
                           service: ConnectionServiceDep) -> ConnectionListResponse:
    return ConnectionListResponse(
        items=[_connection(c) for c in await service.connections(principal.tenant_id)],
        available=service.available(), redirect_uri=service.redirect_uri)


@router.post("", dependencies=[ADMIN], summary="Start connecting Notion or Google Drive",
             description="Send the person to `authorize_url`, in the browser that made this "
                         "request: it keeps a cookie that finishing the sign-in needs. Once "
                         "they sign in and allow reading, they come back to `return_to` with "
                         "`connected=<id>`, or with `connection_error=<signal>`.",
             responses=error_responses(ConnectorNotConfigured))
async def start_connection(body: ConnectionStartRequest, principal: PrincipalDep,
                           service: ConnectionServiceDep, settings: SettingsDep,
                           response: Response) -> ConnectionStartResponse:
    started = await service.start(principal.tenant_id, body.kind, user_id=principal.user_id,
                                  return_to=body.return_to)
    # Lax, unlike the session cookie: the service's redirect back is another site's link.
    response.set_cookie(BROWSER_COOKIE, started.browser_key, max_age=15 * 60,
                        path="/api/v1/connections", httponly=True, samesite="lax",
                        secure=settings.SESSION_COOKIE_SECURE)
    return ConnectionStartResponse(authorize_url=started.authorize_url)


@router.delete("/{connection_id}", dependencies=[ADMIN],
               status_code=status.HTTP_204_NO_CONTENT, summary="Remove a connection",
               description="Its tokens are forgotten. Remove the sources that read through it "
                           "first; revoke the access at the service too, if you like.",
               responses=error_responses(ConnectionNotFound, ConnectionInUse))
async def delete_connection(connection_id: ConnectionIdPath, principal: PrincipalDep,
                            service: ConnectionServiceDep) -> Response:
    await service.delete(principal.tenant_id, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Not for API clients, so not in the schema: it is the OAuth apps' redirect URI, which keeps
# the connection and redirects to the web app.
@public_router.get("/callback", response_class=RedirectResponse,
                   status_code=status.HTTP_303_SEE_OTHER, include_in_schema=False)
async def connection_callback(http_request: Request, session: SessionDep,
                              settings: SettingsDep,
                              state: Annotated[str, Query(max_length=200)] = "",
                              code: Annotated[str | None, Query(max_length=2000)] = None,
                              error: Annotated[str | None, Query(max_length=200)] = None,
                              ) -> RedirectResponse:
    # The provider's redirect carries no sign-in: the single-use state says whose it is.
    service = ConnectionService(SqlUnitOfWork(session), get_oauth_providers(http_request),
                                app_url=settings.APP_URL)
    try:
        pending = await service.find(state)
    except ConnectionRequestInvalid as exc:
        return _back(f"{service.app_url}/admin", connection_error=exc.signal.value)
    # Started on one of the workspace's domains: its cookie is there, so finish there.
    started_on = urlsplit(pending.return_to)
    if started_on.netloc.lower() != http_request.url.netloc.lower():
        return RedirectResponse(
            f"{started_on.scheme}://{started_on.netloc}{CALLBACK_PATH}?{http_request.url.query}",
            status_code=status.HTTP_303_SEE_OTHER)
    try:
        request = await service.take(state, http_request.cookies.get(BROWSER_COOKIE))
    except ConnectionRequestInvalid as exc:
        return _back(pending.return_to, connection_error=exc.signal.value)
    log_context.user.set(request.user_id)
    try:
        connection = await service.connect(request, code, error)
    except AppError as exc:
        logger.info("A %s connection failed: %s", request.kind, exc)
        return _back(request.return_to, connection_error=exc.signal.value)
    return _back(request.return_to, connected=connection.id)


def _back(url: str, **params: str) -> RedirectResponse:
    """Back to the web app, saying how the sign-in went; the sign-in's cookie is done."""
    response = RedirectResponse(with_query(url, **params),
                                status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(BROWSER_COOKIE, path="/api/v1/connections")
    return response
