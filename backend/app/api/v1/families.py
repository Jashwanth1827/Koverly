"""Family, family member, and membership endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, FamilyContext, FamilyCtx, require_role
from app.models.enums import FamilyRole
from app.schemas.common import Message
from app.schemas.family import (
    FamilyAccessOut,
    FamilyCreate,
    FamilyMemberCreate,
    FamilyMemberOut,
    FamilyMemberUpdate,
    FamilyOut,
    FamilyUpdate,
    InviteMember,
    RoleUpdate,
)
from app.services import family_service

router = APIRouter(tags=["families"])

AdminCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.ADMIN))]
MemberCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.MEMBER))]
OwnerCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.OWNER))]


@router.post(
    "/families", response_model=FamilyOut, status_code=status.HTTP_201_CREATED
)
async def create_family(
    payload: FamilyCreate, user: CurrentUser, db: DbSession
) -> FamilyOut:
    family = await family_service.create_family(db, user, payload.name)
    return FamilyOut.model_validate(family)


@router.get("/families", response_model=list[FamilyOut])
async def list_families(user: CurrentUser, db: DbSession) -> list[FamilyOut]:
    families = await family_service.list_families_for_user(db, user)
    return [FamilyOut.model_validate(f) for f in families]


@router.get("/families/{family_id}", response_model=FamilyAccessOut)
async def get_family(ctx: FamilyCtx) -> FamilyAccessOut:
    return FamilyAccessOut(
        family=FamilyOut.model_validate(ctx.family),
        role=ctx.role,
        member_id=ctx.member.id if ctx.member else None,
    )


@router.patch("/families/{family_id}", response_model=FamilyOut)
async def update_family(
    payload: FamilyUpdate, ctx: AdminCtx, db: DbSession
) -> FamilyOut:
    family = await family_service.update_family(
        db, ctx.family, name=payload.name, actor=ctx.user
    )
    return FamilyOut.model_validate(family)


@router.delete("/families/{family_id}", response_model=Message)
async def delete_family(ctx: OwnerCtx, db: DbSession) -> Message:
    await family_service.delete_family(db, ctx.family, ctx.user)
    return Message(message="Family deleted.")


# --------------------------------------------------------------------------- #
# Family members
# --------------------------------------------------------------------------- #
@router.get("/families/{family_id}/members", response_model=list[FamilyMemberOut])
async def list_members(ctx: FamilyCtx, db: DbSession) -> list[FamilyMemberOut]:
    members = await family_service.list_members(db, ctx.family_id)
    return [FamilyMemberOut.model_validate(m) for m in members]


@router.post(
    "/families/{family_id}/members",
    response_model=FamilyMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    payload: FamilyMemberCreate, ctx: MemberCtx, db: DbSession
) -> FamilyMemberOut:
    member = await family_service.add_member(db, ctx.family_id, payload, ctx.user)
    return FamilyMemberOut.model_validate(member)


@router.get(
    "/families/{family_id}/members/{member_id}", response_model=FamilyMemberOut
)
async def get_member(
    member_id: str, ctx: FamilyCtx, db: DbSession
) -> FamilyMemberOut:
    member = await family_service.get_member(db, ctx.family_id, member_id)
    return FamilyMemberOut.model_validate(member)


@router.patch(
    "/families/{family_id}/members/{member_id}", response_model=FamilyMemberOut
)
async def update_member(
    member_id: str,
    payload: FamilyMemberUpdate,
    ctx: MemberCtx,
    db: DbSession,
) -> FamilyMemberOut:
    member = await family_service.update_member(
        db, ctx.family_id, member_id, payload, ctx.user
    )
    return FamilyMemberOut.model_validate(member)


@router.delete(
    "/families/{family_id}/members/{member_id}", response_model=Message
)
async def remove_member(
    member_id: str, ctx: AdminCtx, db: DbSession
) -> Message:
    await family_service.remove_member(db, ctx.family_id, member_id, ctx.user)
    return Message(message="Family member removed.")


@router.post(
    "/families/{family_id}/invites",
    response_model=FamilyMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    payload: InviteMember, ctx: AdminCtx, db: DbSession
) -> FamilyMemberOut:
    member = await family_service.invite_member(
        db,
        ctx.family_id,
        email=str(payload.email),
        role=payload.role,
        member_id=payload.member_id,
        actor=ctx.user,
    )
    return FamilyMemberOut.model_validate(member)


@router.patch(
    "/families/{family_id}/members/{member_id}/role",
    response_model=FamilyMemberOut,
)
async def change_role(
    member_id: str, payload: RoleUpdate, ctx: AdminCtx, db: DbSession
) -> FamilyMemberOut:
    member = await family_service.change_role(
        db, ctx.family_id, member_id, role=payload.role, actor=ctx.user
    )
    return FamilyMemberOut.model_validate(member)
