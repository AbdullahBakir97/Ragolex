"""A workspace's members and invitations, as its admins manage them.

Admins (and API keys with the admin scope) manage editors, viewers and
admins; only a signed-in owner makes someone an owner, or changes or
removes an owner. A workspace always keeps one owner.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ragolex.core.errors import (
    AlreadyMember,
    InvitationNotFound,
    LastOwner,
    MemberNotFound,
    OwnerRequired,
    SsoRequired,
)
from ragolex.domain.models import Invitation, Mail, Member, Principal, User
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.account_service import normalise_email
from ragolex.services.audit import record
from ragolex.services.auth_service import hash_key
from ragolex.services.emails import invitation_mail

# An invitation link works once, for a week.
INVITATION_FOR = timedelta(days=7)


def invitation_link(app_url: str, token: str) -> str:
    # In the fragment, which browsers never send to a server or in a Referer.
    return f"{app_url}/invite#{token}"


@dataclass(frozen=True)
class NewInvitation:
    """An invitation just made: its link (shown once) and the email that can carry it."""

    invitation: Invitation
    inviter: User | None
    link: str
    mail: Mail


class MemberService:

    def __init__(self, uow: UnitOfWork, app_url: str = "http://localhost:3000"):
        self.uow = uow
        self.app_url = app_url

    async def members(self, tenant_id: int) -> list[Member]:
        return await self.uow.memberships.list_for_tenant(tenant_id)

    async def _member(self, tenant_id: int, user_id: int) -> Member:
        membership = await self.uow.memberships.get(user_id, tenant_id)
        user = await self.uow.users.get(user_id) if membership else None
        if membership is None or user is None:
            raise MemberNotFound()
        return Member(user=user, role=membership.role, joined_at=membership.created_at)

    @staticmethod
    def _check_owner(principal: Principal, *roles: str) -> None:
        if "owner" in roles and principal.role != "owner":
            raise OwnerRequired()

    async def _check_not_last_owner(self, tenant_id: int, member: Member) -> None:
        if member.role == "owner" and await self.uow.memberships.count_owners(tenant_id) <= 1:
            raise LastOwner()

    async def change_role(self, principal: Principal, user_id: int, role: str) -> Member:
        tenant_id = principal.tenant_id
        member = await self._member(tenant_id, user_id)
        if member.role == role:
            return member
        self._check_owner(principal, member.role, role)
        await self._check_not_last_owner(tenant_id, member)
        membership = await self.uow.memberships.add(user_id=user_id, tenant_id=tenant_id,
                                                    role=role)
        await record(self.uow, tenant_id, "member.role_changed", member.user.email,
                     role=role, previous_role=member.role)
        await self.uow.commit()
        return Member(user=member.user, role=membership.role, joined_at=member.joined_at)

    async def remove(self, principal: Principal, user_id: int) -> None:
        """Take the member out of the workspace; their sessions in it end at once."""
        tenant_id = principal.tenant_id
        member = await self._member(tenant_id, user_id)
        self._check_owner(principal, member.role)
        await self._check_not_last_owner(tenant_id, member)
        await self.uow.memberships.remove(user_id, tenant_id)
        await self.uow.user_sessions.delete_for_user(user_id, tenant_id=tenant_id)
        await record(self.uow, tenant_id, "member.removed", member.user.email,
                     role=member.role)
        await self.uow.commit()

    async def invite(self, principal: Principal, email: str, role: str) -> NewInvitation:
        """An invitation for ``email``, in place of any it had; refused for members."""
        self._check_owner(principal, role)
        tenant_id = principal.tenant_id
        provider = await self.uow.sso.get(tenant_id)
        if provider is not None and provider.enforced:
            raise SsoRequired("This workspace's members join through single sign-on")
        address = normalise_email(email)
        login = await self.uow.users.login(address)
        if login and await self.uow.memberships.get(login.user.id, tenant_id):
            raise AlreadyMember()
        token = secrets.token_urlsafe(32)
        invitation = await self.uow.invitations.create(
            tenant_id=tenant_id, email=address, role=role, token_hash=hash_key(token),
            invited_by=principal.user_id, expires_at=datetime.now(UTC) + INVITATION_FOR)
        await record(self.uow, tenant_id, "invitation.created", address,
                     invitation=invitation.id, role=role)
        await self.uow.commit()
        # On this server's address, as password reset links are: a workspace's domain may
        # pass to someone else (it lapses, or is pointed elsewhere), and the link with it.
        link = invitation_link(self.app_url, token)
        inviter = await self.uow.users.get(principal.user_id) if principal.user_id else None
        return NewInvitation(invitation=invitation, inviter=inviter, link=link,
                             mail=invitation_mail(invitation, link, inviter))

    async def invitations(self, tenant_id: int) -> list[tuple[Invitation, User | None]]:
        """The invitations not accepted yet, expired ones too, with who sent each."""
        pending = await self.uow.invitations.list_pending(tenant_id)
        senders = {i.invited_by: await self.uow.users.get(i.invited_by)
                   for i in pending if i.invited_by}
        return [(i, senders[i.invited_by] if i.invited_by else None) for i in pending]

    async def revoke(self, tenant_id: int, invitation_id: str) -> None:
        """The link stops working at once."""
        invitations = await self.uow.invitations.list_pending(tenant_id)
        invitation = next((i for i in invitations if i.id == invitation_id), None)
        if invitation is None or not await self.uow.invitations.delete(tenant_id, invitation_id):
            raise InvitationNotFound()
        await record(self.uow, tenant_id, "invitation.revoked", invitation.email,
                     invitation=invitation.id, role=invitation.role)
        await self.uow.commit()
