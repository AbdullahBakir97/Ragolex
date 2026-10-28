"""People's accounts: signing up, in and out, and the workspaces they work in.

A signed-in browser holds a random session token in a cookie; only its
SHA-256 is stored, as for API keys. What a user may do in a workspace comes
from their role there (ROLE_SCOPES), so roles and API keys share the same
checks.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ragolex.core import log_context
from ragolex.core.errors import (
    AccountLocked,
    EmailTaken,
    LoginFailed,
    SessionRequired,
    WorkspaceNotFound,
    WorkspaceTaken,
)
from ragolex.core.passwords import hash_password, needs_rehash, verify_password
from ragolex.domain.models import ROLE_SCOPES, Membership, Principal, User, UserSession
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record
from ragolex.services.auth_service import hash_key

# The 10th failed sign-in in a row locks the account for 15 minutes: slow enough
# to stop guessing, short enough not to lock someone out for long.
LOCK_AFTER = 10
LOCK_FOR = timedelta(minutes=15)


def normalise_email(email: str) -> str:
    """One address, one account: email addresses are compared in lower case."""
    return email.strip().lower()


@dataclass(frozen=True)
class SignedIn:
    """A user's session: the token for the cookie (shown once), and where it works."""

    user: User
    session: UserSession
    workspace: Membership
    workspaces: list[Membership]
    token: str


class AccountService:

    def __init__(self, uow: UnitOfWork, session_days: int):
        self.uow = uow
        self.session_length = timedelta(days=session_days)

    async def sign_up(self, *, email: str, password: str, name: str,
                      workspace: str) -> SignedIn:
        """A new account with a workspace of its own, which it owns; signed in.

        Both are created only if new: two sign-ups racing for one workspace name
        cannot both own it. Nothing is saved unless all of it is.
        """
        tenant = await self.uow.tenants.create(workspace)
        if tenant is None:
            raise WorkspaceTaken()
        user = await self.uow.users.create(email=normalise_email(email), name=name.strip(),
                                           password_hash=hash_password(password))
        if user is None:
            raise EmailTaken()
        membership = await self.uow.memberships.add(user_id=user.id, tenant_id=tenant.id,
                                                    role="owner")
        # The new user did this, so the audit log names them.
        log_context.user.set(user.id)
        await record(self.uow, tenant.id, "tenant.created", tenant.name)
        await record(self.uow, tenant.id, "member.added", user.email, role="owner")
        await self.uow.users.logged_in(user.id)
        return await self._start(user, membership)

    async def sign_in(self, email: str, password: str) -> SignedIn:
        """A new session for the account; raises LoginFailed or AccountLocked."""
        login = await self.uow.users.login(normalise_email(email))
        if login and login.locked_until and login.locked_until > datetime.now(UTC):
            raise AccountLocked()
        if not verify_password(login.password_hash if login else None, password):
            if login:
                await self.uow.users.login_failed(login.user.id, lock_after=LOCK_AFTER,
                                                  lock_for=LOCK_FOR)
                await self.uow.commit()
            raise LoginFailed()
        assert login is not None
        user = login.user
        if needs_rehash(login.password_hash):
            await self.uow.users.set_password(user.id, hash_password(password))
        await self.uow.users.logged_in(user.id)
        workspaces = await self.uow.memberships.list_for_user(user.id)
        if not workspaces:
            await self.uow.commit()
            raise WorkspaceNotFound("You are not a member of any workspace")
        return await self._start(user, workspaces[0])

    async def _start(self, user: User, membership: Membership) -> SignedIn:
        token = secrets.token_urlsafe(32)
        session = await self.uow.user_sessions.create(
            user_id=user.id, tenant_id=membership.tenant_id, token_hash=hash_key(token),
            expires_at=datetime.now(UTC) + self.session_length)
        workspaces = await self.uow.memberships.list_for_user(user.id)
        await self.uow.commit()
        return SignedIn(user=user, session=session, workspace=membership,
                        workspaces=workspaces, token=token)

    async def _session(self, token: str | None) -> tuple[UserSession, User, Membership]:
        session = await self.uow.user_sessions.find_active(hash_key(token)) if token else None
        user = await self.uow.users.get(session.user_id) if session else None
        membership = (await self.uow.memberships.get(user.id, session.tenant_id)
                      if session and user else None)
        if session is None or user is None or membership is None:
            raise SessionRequired()
        return session, user, membership

    async def authenticate(self, token: str | None) -> Principal:
        """Who a session acts for: its user, with their role in its workspace."""
        session, user, membership = await self._session(token)
        await self.uow.user_sessions.touch(session.id)
        await self.uow.commit()
        return Principal(tenant_id=membership.tenant_id, tenant_name=membership.tenant_name,
                         scopes=ROLE_SCOPES[membership.role], user_id=user.id,
                         role=membership.role)

    async def current(self, token: str | None) -> SignedIn:
        """The session's user and workspaces (its token is not returned again)."""
        session, user, membership = await self._session(token)
        return SignedIn(user=user, session=session, workspace=membership,
                        workspaces=await self.uow.memberships.list_for_user(user.id), token="")

    async def switch_workspace(self, token: str | None, workspace: str) -> SignedIn:
        """Work in another of the user's workspaces; raises WorkspaceNotFound otherwise."""
        session, user, _ = await self._session(token)
        workspaces = await self.uow.memberships.list_for_user(user.id)
        target = next((m for m in workspaces if m.tenant_name == workspace), None)
        if target is None:
            raise WorkspaceNotFound()
        await self.uow.user_sessions.switch_tenant(session.id, target.tenant_id)
        await self.uow.commit()
        return SignedIn(user=user, session=session, workspace=target, workspaces=workspaces,
                        token="")

    async def sign_out(self, token: str | None) -> None:
        session = await self.uow.user_sessions.find_active(hash_key(token)) if token else None
        if session is not None:
            await self.uow.user_sessions.delete(session.id)
            await self.uow.commit()

    async def add_member(self, *, email: str, tenant_name: str, role: str, name: str | None,
                         password: str | None) -> tuple[User, bool]:
        """For the command line: give an account (made if new) a role in a tenant.

        Returns the user and whether the account is new; a new one needs ``password``.
        """
        tenant = await self.uow.tenants.get_by_name(tenant_name)
        if tenant is None:
            raise WorkspaceNotFound()
        address = normalise_email(email)
        login = await self.uow.users.login(address)
        created = login is None
        if login is None:
            if not password:
                raise ValueError("A new account needs a password")
            user = await self.uow.users.create(email=address, name=(name or address).strip(),
                                               password_hash=hash_password(password))
            if user is None:  # Created meanwhile by another request.
                raise EmailTaken()
        else:
            user = login.user
        await self.uow.memberships.add(user_id=user.id, tenant_id=tenant.id, role=role)
        await record(self.uow, tenant.id, "member.added", user.email, role=role)
        await self.uow.commit()
        return user, created
