"""Signing up, in and out: people's accounts, the workspaces they work in, and passwords.

A signed-in browser gets an HttpOnly session cookie; it acts in one of the
user's workspaces at a time, with what their role there allows. API keys
work as before, alongside. Invitation and reset tokens travel in request
bodies, never in URLs, so they stay out of access logs.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Response, Security, status

from ragolex.api.dependencies import (
    ACCOUNTS_ON,
    SESSION_COOKIE,
    AccountServiceDep,
    MailerDep,
    SettingsDep,
    session_cookie,
)
from ragolex.api.schemas import (
    AcceptInvitationRequest,
    InvitationPreviewResponse,
    InvitationTokenRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionResponse,
    SignupRequest,
    UserResponse,
    WorkspaceRequest,
    WorkspaceResponse,
    error_responses,
)
from ragolex.core.config import Settings
from ragolex.core.errors import (
    AccountDetailsRequired,
    AccountLocked,
    AccountsDisabled,
    CurrentPasswordWrong,
    EmailTaken,
    InvitationForSomeoneElse,
    InvitationInvalid,
    LoginFailed,
    PasswordResetInvalid,
    SessionRequired,
    SignupDisabled,
    WorkspaceNotFound,
    WorkspaceTaken,
)
from ragolex.domain.models import Membership
from ragolex.services.account_service import SignedIn
from ragolex.services.emails import send_mail

router = APIRouter(prefix="/api/v1/auth", tags=["accounts"], dependencies=[ACCOUNTS_ON])

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


@router.post("/invitation", summary="What an invitation link offers",
             description="For the invitation page, before accepting: the workspace, the role, "
                         "and whether the email has an account to sign in with. A `POST`, so "
                         "the token stays out of URLs and logs.",
             responses=error_responses(AccountsDisabled, InvitationInvalid))
async def invitation(request: InvitationTokenRequest,
                     accounts: AccountServiceDep) -> InvitationPreviewResponse:
    preview = await accounts.invitation(request.token)
    found = preview.invitation
    return InvitationPreviewResponse(
        workspace=found.tenant_name, email=found.email, role=found.role,  # type: ignore[arg-type]
        invited_by=preview.inviter.name if preview.inviter else None,
        expires_at=found.expires_at, has_account=preview.has_account)


@router.post("/invitation/accept", summary="Accept an invitation, and work in its workspace",
             description="Signed in, the invitation must be for the user's email. Not signed "
                         "in, it makes the invited email's account from `name` and `password`, "
                         "and signs in (setting the session cookie); an email that has an "
                         "account signs in first. Works even with `SIGNUP_ENABLED` off.",
             responses=error_responses(AccountsDisabled, InvitationInvalid,
                                       InvitationForSomeoneElse, SessionRequired,
                                       AccountDetailsRequired, EmailTaken))
async def accept_invitation(request: AcceptInvitationRequest, response: Response,
                            cookie: CookieDep, accounts: AccountServiceDep,
                            settings: SettingsDep) -> SessionResponse:
    signed_in = await accounts.accept_invitation(request.token, session_token=cookie,
                                                 name=request.name, password=request.password)
    if signed_in.token:
        _set_cookie(response, signed_in, settings)
    return _session(signed_in)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED,
             summary="Email a link to choose a new password",
             description="Always answers `202`, whether the address has an account or not, so "
                         "it tells nobody which do. With `SMTP_HOST` set, the account gets a "
                         "link that works once, for an hour; at most one a minute is sent. "
                         "Without email, operators make a link with `ragolex users "
                         "reset-password`.",
             responses=error_responses(AccountsDisabled))
async def request_password_reset(request: PasswordResetRequest, accounts: AccountServiceDep,
                                 mailer: MailerDep, background: BackgroundTasks) -> Response:
    if mailer is not None:
        mail = await accounts.request_password_reset(request.email)
        if mail is not None:
            background.add_task(send_mail, mailer, mail)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT,
             summary="Choose a new password with a reset link",
             description="Every session of the account ends; sign in with the new password.",
             responses=error_responses(AccountsDisabled, PasswordResetInvalid))
async def reset_password(request: PasswordResetConfirmRequest,
                         accounts: AccountServiceDep) -> Response:
    await accounts.reset_password(request.token, request.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT,
            summary="Change the signed-in user's password",
            description="Needs the current password; a wrong one counts as a failed sign-in. "
                        "The user's other sessions end; this one stays.",
            responses=error_responses(AccountsDisabled, SessionRequired, CurrentPasswordWrong,
                                      AccountLocked))
async def change_password(request: PasswordChangeRequest, cookie: CookieDep,
                          accounts: AccountServiceDep) -> Response:
    await accounts.change_password(cookie, request.current_password, request.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
