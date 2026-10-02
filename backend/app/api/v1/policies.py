"""Policy endpoints — CRUD, listing, and dashboard summary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, FamilyContext, FamilyCtx, require_role
from app.models.enums import FamilyRole
from app.schemas.common import Message, Page
from app.schemas.policy import (
    PolicyCreate,
    PolicyOut,
    PolicySummary,
    PolicyUpdate,
)
from app.services import policy_service

router = APIRouter(prefix="/families/{family_id}/policies", tags=["policies"])

WriterCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.MEMBER))]
AdminCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.ADMIN))]


@router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreate, ctx: WriterCtx, db: DbSession
) -> PolicyOut:
    payload.family_id = ctx.family_id
    policy = await policy_service.create_policy(db, payload, ctx.user)
    return PolicyOut.model_validate(policy)


@router.get("", response_model=Page[PolicyOut])
async def list_policies(
    ctx: FamilyCtx,
    db: DbSession,
    policy_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    member_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[PolicyOut]:
    items, total = await policy_service.list_policies(
        db,
        ctx.family_id,
        policy_type=policy_type,
        status=status_filter,
        member_id=member_id,
        search=search,
        sort=sort,
        order=order,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[PolicyOut](
        items=[PolicyOut.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=PolicySummary)
async def policy_summary(ctx: FamilyCtx, db: DbSession) -> PolicySummary:
    summary = await policy_service.aggregate_summary(db, ctx.family_id)
    return PolicySummary(**summary)


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(
    policy_id: str, ctx: FamilyCtx, db: DbSession
) -> PolicyOut:
    policy = await policy_service.get_policy(db, ctx.family_id, policy_id)
    return PolicyOut.model_validate(policy)


@router.patch("/{policy_id}", response_model=PolicyOut)
async def update_policy(
    policy_id: str, payload: PolicyUpdate, ctx: WriterCtx, db: DbSession
) -> PolicyOut:
    policy = await policy_service.update_policy(
        db, ctx.family_id, policy_id, payload, ctx.user
    )
    return PolicyOut.model_validate(policy)


@router.delete("/{policy_id}", response_model=Message)
async def delete_policy(
    policy_id: str,
    ctx: AdminCtx,
    db: DbSession,
) -> Message:
    await policy_service.delete_policy(db, ctx.family_id, policy_id, ctx.user)
    return Message(message="Policy deleted.")
