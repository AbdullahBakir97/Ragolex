"""Signing up, in and out: people's accounts and the workspaces they work in.

A signed-in browser gets an HttpOnly session cookie; it acts in one of the
user's workspaces at a time, with what their role there allows. API keys
work as before, alongside.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, Security, status

from ragolex.api.dependencies import (
    SESSION_COOKIE,
    AccountServiceDep,
    SettingsDep,
    session_cookie,
)
from ragolex.api.schemas import (
    LoginRequest,
    SessionResponse,
    SignupRequest,
    UserResponse,
    WorkspaceRequest,
    WorkspaceResponse,
    error_responses,
)
from ragolex.core.config import Settings, get_settings
from ragolex.core.errors import (
    AccountLocked,
    AccountsDisabled,
    EmailTaken,
    LoginFailed,
    SessionRequired,
    SignupDisabled,
    WorkspaceNotFound,
    WorkspaceTaken,
)
from ragolex.domain.models import Membership
from ragolex.services.account_service import SignedIn


def accounts_on(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Accounts need authentication on; without it everyone is the default tenant."""
    if not settings.AUTH_ENABLED:
        raise AccountsDisabled()


router = APIRouter(prefix="/api/v1/auth", tags=["accounts"], dependencies=[Depends(accounts_on)])

CookieDep = Annotated[str | None, Security(session_cookie)]


def _workspace(membership: Membership) -> WorkspaceResponse:
    return WorkspaceResponse(name=membership.tenant_name, role=membership.role)  # type: ignore[arg-type]


def _session(signed_in: SignedIn) -> SessionResponse:
    user = signed_in.user
    return SessionResponse(user=UserResponse(id=user.id, email=user.email, name=user.name),
                           workspace=_workspace(signed_in.workspace),
                           workspaces=[_workspace(m) for m in signed_in.workspaces],
                           expires_at=signed_in.session.expires_at)


def _set_cookie(response: Response, signed_in: SignedIn, settings: Settings) -> None:
    # HttpOnly: scripts cannot read it. SameSite=Strict: other sites cannot send it,
    # which keeps them from acting for the user (CSRF). Only sent to the API.
    response.set_cookie(SESSION_COOKIE, signed_in.token, max_age=settings.SESSION_DAYS * 86400,
                        path="/api", httponly=True, samesite="strict",
                        secure=settings.SESSION_COOKIE_SECURE)


@router.post("/signup", status_code=status.HTTP_201_CREATED,
             summary="Create an account with a workspace of its own, and sign in",
             description="The new user owns the new workspace. Sets the session cookie. "
                         "Off when the server's `SIGNUP_ENABLED` is.",
             responses=error_responses(AccountsDisabled, SignupDisabled, EmailTaken,
                                       WorkspaceTaken))
async def sign_up(request: SignupRequest, response: Response, accounts: AccountServiceDep,
                  settings: SettingsDep) -> SessionResponse:
    if not settings.SIGNUP_ENABLED:
        raise SignupDisabled()
    signed_in = await accounts.sign_up(email=request.email, password=request.password,
                                       name=request.name, workspace=request.workspace)
    _set_cookie(response, signed_in, settings)
    return _session(signed_in)


@router.post("/login", summary="Sign in with an email and password",
             description="Sets the session cookie, working in the first of the user's "
                         "workspaces. The 10th wrong password in a row locks the account "
                         "for 15 minutes.",
             responses=error_responses(AccountsDisabled, LoginFailed, AccountLocked,
                                       WorkspaceNotFound))
async def sign_in(request: LoginRequest, response: Response, accounts: AccountServiceDep,
                  settings: SettingsDep) -> SessionResponse:
    signed_in = await accounts.sign_in(request.email, request.password)
    _set_cookie(response, signed_in, settings)
    return _session(signed_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="Sign out: end the session and remove its cookie",
             responses=error_responses(AccountsDisabled))
async def sign_out(cookie: CookieDep, accounts: AccountServiceDep) -> Response:
    await accounts.sign_out(cookie)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/api")
    return response


@router.get("/session", summary="The signed-in user and their workspaces",
            responses=error_responses(AccountsDisabled, SessionRequired))
async def current_session(cookie: CookieDep, accounts: AccountServiceDep) -> SessionResponse:
    return _session(await accounts.current(cookie))


@router.put("/session/workspace", summary="Work in another of the user's workspaces",
            responses=error_responses(AccountsDisabled, SessionRequired, WorkspaceNotFound))
async def switch_workspace(request: WorkspaceRequest, cookie: CookieDep,
                           accounts: AccountServiceDep) -> SessionResponse:
    return _session(await accounts.switch_workspace(cookie, request.workspace))
