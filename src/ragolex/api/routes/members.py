"""A workspace's members and invitations, for its admins.

These need accounts (AUTH_ENABLED) and the admin scope: an owner's or an
admin's session, or an API key with the admin scope. Only a signed-in owner
makes or changes owners.
"""

from fastapi import APIRouter, BackgroundTasks, Response, status

from ragolex.api.dependencies import (
    ACCOUNTS_ON,
    ADMIN,
    MailerDep,
    MemberServiceDep,
    PrincipalDep,
)
from ragolex.api.schemas import (
    InvitationCreatedResponse,
    InvitationIdPath,
    InvitationRequest,
    InvitationResponse,
    MemberResponse,
    RoleRequest,
    UserIdPath,
    UserResponse,
    error_responses,
)
from ragolex.core.errors import (
    AccountsDisabled,
    AlreadyMember,
    InvitationNotFound,
    LastOwner,
    MemberNotFound,
    OwnerRequired,
)
from ragolex.domain.models import Invitation, Member, User
from ragolex.services.emails import send_mail

router = APIRouter(prefix="/api/v1", tags=["members"], dependencies=[ACCOUNTS_ON, ADMIN],
                   responses=error_responses(AccountsDisabled))


def _member(member: Member) -> MemberResponse:
    user = member.user
    return MemberResponse(id=user.id, email=user.email, name=user.name,
                          role=member.role,  # type: ignore[arg-type]
                          joined_at=member.joined_at, last_login_at=user.last_login_at)


def _invitation(invitation: Invitation, inviter: User | None) -> dict:
    return {"id": invitation.id, "email": invitation.email, "role": invitation.role,
            "invited_by": UserResponse(id=inviter.id, email=inviter.email, name=inviter.name)
            if inviter else None,
            "created_at": invitation.created_at, "expires_at": invitation.expires_at}


@router.get("/members", summary="The workspace's members, by email")
async def list_members(principal: PrincipalDep,
                       service: MemberServiceDep) -> list[MemberResponse]:
    return [_member(member) for member in await service.members(principal.tenant_id)]


@router.put("/members/{user_id}", summary="Change a member's role",
            description="Their sessions get the new role with their next request.",
            responses=error_responses(MemberNotFound, OwnerRequired, LastOwner))
async def change_role(user_id: UserIdPath, request: RoleRequest, principal: PrincipalDep,
                      service: MemberServiceDep) -> MemberResponse:
    return _member(await service.change_role(principal, user_id, request.role))


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a member from the workspace",
               description="Their account stays; their sessions in this workspace end at once.",
               responses=error_responses(MemberNotFound, OwnerRequired, LastOwner))
async def remove_member(user_id: UserIdPath, principal: PrincipalDep,
                        service: MemberServiceDep) -> Response:
    await service.remove(principal, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations", summary="Invitations not accepted yet, newest first",
            description="Expired ones too, until they are revoked or sent again.")
async def list_invitations(principal: PrincipalDep,
                           service: MemberServiceDep) -> list[InvitationResponse]:
    return [InvitationResponse(**_invitation(invitation, inviter))
            for invitation, inviter in await service.invitations(principal.tenant_id)]


@router.post("/invitations", status_code=status.HTTP_201_CREATED,
             summary="Invite someone to the workspace by email",
             description="Returns a link to send them, valid once for a week; with "
                         "`SMTP_HOST` set, it is emailed to them too. Inviting the same "
                         "address again replaces its earlier link.",
             responses=error_responses(OwnerRequired, AlreadyMember))
async def invite(request: InvitationRequest, principal: PrincipalDep, service: MemberServiceDep,
                 mailer: MailerDep, background: BackgroundTasks) -> InvitationCreatedResponse:
    new = await service.invite(principal, request.email, request.role)
    if mailer is not None:
        background.add_task(send_mail, mailer, new.mail)
    return InvitationCreatedResponse(**_invitation(new.invitation, new.inviter), link=new.link,
                                     emailed=mailer is not None)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke an invitation", description="Its link stops working at once.",
               responses=error_responses(InvitationNotFound))
async def revoke_invitation(invitation_id: InvitationIdPath, principal: PrincipalDep,
                            service: MemberServiceDep) -> Response:
    await service.revoke(principal.tenant_id, str(invitation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
