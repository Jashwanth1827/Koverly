"""Claim service — CRUD, status transitions, timeline."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.claim import Claim, ClaimEvent
from app.models.enums import AuditAction, ClaimStatus
from app.models.family import FamilyMember
from app.models.policy import Policy
from app.models.user import User
from app.schemas.claim import ClaimCreate, ClaimUpdate
from app.services import audit

# Allowed status transitions. Prevents nonsensical jumps and documents the
# claim lifecycle.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ClaimStatus.DRAFT.value: {ClaimStatus.SUBMITTED.value, ClaimStatus.CLOSED.value},
    ClaimStatus.SUBMITTED.value: {
        ClaimStatus.DOCUMENTS_REQUIRED.value,
        ClaimStatus.UNDER_REVIEW.value,
        ClaimStatus.REJECTED.value,
    },
    ClaimStatus.DOCUMENTS_REQUIRED.value: {
        ClaimStatus.UNDER_REVIEW.value,
        ClaimStatus.REJECTED.value,
    },
    ClaimStatus.UNDER_REVIEW.value: {
        ClaimStatus.APPROVED.value,
        ClaimStatus.REJECTED.value,
    },
    ClaimStatus.APPROVED.value: {ClaimStatus.SETTLED.value, ClaimStatus.CLOSED.value},
    ClaimStatus.SETTLED.value: {ClaimStatus.CLOSED.value},
    ClaimStatus.REJECTED.value: {ClaimStatus.CLOSED.value},
    ClaimStatus.CLOSED.value: set(),
}


async def get_claim(db: AsyncSession, family_id: str, claim_id: str) -> Claim:
    claim = await db.get(Claim, claim_id)
    if claim is None or claim.family_id != family_id:
        raise NotFoundError("Claim not found.")
    return claim


async def get_claim_detail(
    db: AsyncSession, family_id: str, claim_id: str
) -> Claim:
    claim = await get_claim(db, family_id, claim_id)
    # Eager-load the timeline ordering.
    await db.refresh(claim, attribute_names=["events"])
    return claim


async def create_claim(
    db: AsyncSession, payload: ClaimCreate, actor: User
) -> Claim:
    policy = await db.get(Policy, payload.policy_id)
    if policy is None or policy.family_id != payload.family_id:
        raise ValidationError("The selected policy does not exist.")
    if payload.member_id:
        member = await db.get(FamilyMember, payload.member_id)
        if member is None or member.family_id != payload.family_id:
            raise ValidationError("The selected family member does not exist.")

    claim = Claim(
        family_id=payload.family_id,
        policy_id=payload.policy_id,
        member_id=payload.member_id,
        created_by_user_id=actor.id,
        claim_type=payload.claim_type,
        claim_amount=payload.claim_amount,
        provider=payload.provider,
        incident_date=payload.incident_date,
        submission_date=payload.submission_date,
        description=payload.description,
        notes=payload.notes,
        metadata_json=payload.metadata_json,
        status=ClaimStatus.DRAFT.value,
    )
    db.add(claim)
    await db.flush()
    db.add(
        ClaimEvent(
            claim_id=claim.id,
            status=ClaimStatus.DRAFT.value,
            note="Claim created.",
            actor_user_id=actor.id,
        )
    )
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.CLAIM_CREATED.value,
        resource_type="claim",
        resource_id=claim.id,
        actor_user_id=actor.id,
        family_id=payload.family_id,
        metadata={"claim_type": claim.claim_type, "policy_id": policy.id},
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def update_claim(
    db: AsyncSession,
    family_id: str,
    claim_id: str,
    payload: ClaimUpdate,
    actor: User,
) -> Claim:
    claim = await get_claim(db, family_id, claim_id)
    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    for field, value in data.items():
        setattr(claim, field, value)
    if new_status is not None:
        target = new_status.value if isinstance(new_status, ClaimStatus) else new_status
        await _transition(db, claim, target, actor)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.CLAIM_UPDATED.value,
        resource_type="claim",
        resource_id=claim.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"fields": sorted(data.keys())},
    )
    await db.commit()
    await db.refresh(claim)
    return claim


async def _transition(
    db: AsyncSession, claim: Claim, target: str, actor: User
) -> None:
    if target == claim.status:
        return
    allowed = _ALLOWED_TRANSITIONS.get(claim.status, set())
    if target not in allowed:
        raise ValidationError(
            f"Cannot change claim status from {claim.status} to {target}."
        )
    claim.status = target
    db.add(
        ClaimEvent(
            claim_id=claim.id,
            status=target,
            note=None,
            actor_user_id=actor.id,
        )
    )


async def delete_claim(
    db: AsyncSession, family_id: str, claim_id: str, actor: User
) -> None:
    claim = await get_claim(db, family_id, claim_id)
    await db.delete(claim)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.CLAIM_UPDATED.value,
        resource_type="claim",
        resource_id=claim_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"deleted": True},
    )
    await db.commit()


async def list_claims(
    db: AsyncSession,
    family_id: str,
    *,
    status: str | None = None,
    policy_id: str | None = None,
    member_id: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Claim], int]:
    stmt = select(Claim).where(Claim.family_id == family_id)
    count_stmt = select(func.count(Claim.id)).where(Claim.family_id == family_id)
    if status:
        stmt = stmt.where(Claim.status == status)
        count_stmt = count_stmt.where(Claim.status == status)
    if policy_id:
        stmt = stmt.where(Claim.policy_id == policy_id)
        count_stmt = count_stmt.where(Claim.policy_id == policy_id)
    if member_id:
        stmt = stmt.where(Claim.member_id == member_id)
        count_stmt = count_stmt.where(Claim.member_id == member_id)
    stmt = stmt.order_by(Claim.created_at.desc()).offset(offset).limit(limit)
    items = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return items, total


async def recent_claims(
    db: AsyncSession, family_id: str, limit: int = 5
) -> list[Claim]:
    rows = await db.execute(
        select(Claim)
        .where(Claim.family_id == family_id)
        .order_by(Claim.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())
