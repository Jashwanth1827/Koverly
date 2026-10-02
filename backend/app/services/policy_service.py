"""Policy service — CRUD, filtering, dashboard aggregation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    PolicyStatus,
    PolicyType,
    PremiumFrequency,
)
from app.models.family import FamilyMember
from app.models.policy import Policy
from app.models.user import User
from app.schemas.policy import PolicyCreate, PolicyUpdate
from app.services import audit

# Annualization factors for premium aggregation.
_FREQUENCY_MULTIPLIER: dict[str, Decimal] = {
    PremiumFrequency.MONTHLY.value: Decimal(12),
    PremiumFrequency.QUARTERLY.value: Decimal(4),
    PremiumFrequency.HALF_YEARLY.value: Decimal(2),
    PremiumFrequency.YEARLY.value: Decimal(1),
    PremiumFrequency.SINGLE.value: Decimal(1),
}


async def get_policy(db: AsyncSession, family_id: str, policy_id: str) -> Policy:
    policy = await db.get(Policy, policy_id)
    if policy is None or policy.family_id != family_id:
        raise NotFoundError("Policy not found.")
    return policy


async def _validate_member(
    db: AsyncSession, family_id: str, member_id: str | None
) -> None:
    if member_id is None:
        return
    member = await db.get(FamilyMember, member_id)
    if member is None or member.family_id != family_id:
        raise ValidationError("The selected family member does not exist.")


async def create_policy(
    db: AsyncSession, payload: PolicyCreate, actor: User
) -> Policy:
    await _validate_member(db, payload.family_id, payload.member_id)
    data = payload.model_dump()
    data["policy_type"] = (
        payload.policy_type.value
        if isinstance(payload.policy_type, PolicyType)
        else payload.policy_type
    )
    data["status"] = (
        payload.status.value if isinstance(payload.status, PolicyStatus) else payload.status
    )
    data["premium_frequency"] = (
        payload.premium_frequency.value if payload.premium_frequency else None
    )
    data.pop("family_id", None)
    policy = Policy(
        family_id=payload.family_id,
        created_by_user_id=actor.id,
        **data,
    )
    db.add(policy)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_CREATED.value,
        resource_type="policy",
        resource_id=policy.id,
        actor_user_id=actor.id,
        family_id=payload.family_id,
        metadata={"insurer": policy.insurer, "policy_type": policy.policy_type},
    )
    await db.commit()
    await db.refresh(policy)
    return policy


async def update_policy(
    db: AsyncSession,
    family_id: str,
    policy_id: str,
    payload: PolicyUpdate,
    actor: User,
) -> Policy:
    policy = await get_policy(db, family_id, policy_id)
    data = payload.model_dump(exclude_unset=True)
    if "member_id" in data:
        await _validate_member(db, family_id, data["member_id"])
    for field in ("policy_type", "status", "premium_frequency"):
        if field in data and data[field] is not None and hasattr(data[field], "value"):
            data[field] = data[field].value
    for field, value in data.items():
        setattr(policy, field, value)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_UPDATED.value,
        resource_type="policy",
        resource_id=policy.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"fields": sorted(data.keys())},
    )
    await db.commit()
    await db.refresh(policy)
    return policy


async def delete_policy(
    db: AsyncSession, family_id: str, policy_id: str, actor: User
) -> None:
    policy = await get_policy(db, family_id, policy_id)
    await db.delete(policy)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_DELETED.value,
        resource_type="policy",
        resource_id=policy_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"insurer": policy.insurer},
    )
    await db.commit()


async def list_policies(
    db: AsyncSession,
    family_id: str,
    *,
    policy_type: str | None = None,
    status: str | None = None,
    member_id: str | None = None,
    search: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Policy], int]:
    stmt = select(Policy).where(Policy.family_id == family_id)
    count_stmt = select(func.count(Policy.id)).where(Policy.family_id == family_id)

    if policy_type:
        stmt = stmt.where(Policy.policy_type == policy_type)
        count_stmt = count_stmt.where(Policy.policy_type == policy_type)
    if status:
        stmt = stmt.where(Policy.status == status)
        count_stmt = count_stmt.where(Policy.status == status)
    if member_id:
        stmt = stmt.where(Policy.member_id == member_id)
        count_stmt = count_stmt.where(Policy.member_id == member_id)
    if search:
        like = f"%{search.lower()}%"
        cond = or_(
            func.lower(Policy.insurer).like(like),
            func.lower(Policy.policy_number).like(like),
            func.lower(Policy.policyholder_name).like(like),
            func.lower(Policy.nominee).like(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    allowed_sort = {
        "created_at": Policy.created_at,
        "expiry_date": Policy.expiry_date,
        "renewal_date": Policy.renewal_date,
        "premium": Policy.premium,
        "sum_insured": Policy.sum_insured,
        "insurer": Policy.insurer,
    }
    column = allowed_sort.get(sort, Policy.created_at)
    stmt = stmt.order_by(column.asc() if order == "asc" else column.desc())
    stmt = stmt.offset(offset).limit(limit)

    items = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return items, total


def annualized_premium(policy: Policy) -> Decimal:
    if policy.premium is None:
        return Decimal(0)
    multiplier = _FREQUENCY_MULTIPLIER.get(
        policy.premium_frequency or "", Decimal(1)
    )
    return Decimal(policy.premium) * multiplier


async def aggregate_summary(db: AsyncSession, family_id: str) -> dict:
    rows = await db.execute(
        select(Policy).where(
            Policy.family_id == family_id, Policy.status == PolicyStatus.ACTIVE.value
        )
    )
    policies = list(rows.scalars().all())

    total_premium = sum((annualized_premium(p) for p in policies), Decimal(0))
    life = sum(
        (Decimal(p.sum_insured or 0) for p in policies if p.policy_type == PolicyType.LIFE.value),
        Decimal(0),
    )
    health = sum(
        (
            Decimal(p.sum_insured or 0)
            for p in policies
            if p.policy_type == PolicyType.HEALTH.value
        ),
        Decimal(0),
    )
    other_types = {
        PolicyType.MOTOR.value,
        PolicyType.HOME.value,
        PolicyType.TRAVEL.value,
        PolicyType.PERSONAL_ACCIDENT.value,
        PolicyType.OTHER.value,
    }
    other = sum(
        (
            Decimal(p.sum_insured or 0)
            for p in policies
            if p.policy_type in other_types
        ),
        Decimal(0),
    )
    by_type: dict[str, int] = {}
    for p in policies:
        by_type[p.policy_type] = by_type.get(p.policy_type, 0) + 1

    return {
        "active_policies": len(policies),
        "total_annual_premium": total_premium,
        "total_life_coverage": life,
        "total_health_coverage": health,
        "total_other_coverage": other,
        "by_type": by_type,
    }


async def policies_expiring_within(
    db: AsyncSession, family_id: str, days: int
) -> list[Policy]:
    today = date.today()
    horizon = today + timedelta(days=days)
    rows = await db.execute(
        select(Policy)
        .where(
            Policy.family_id == family_id,
            Policy.status == PolicyStatus.ACTIVE.value,
            Policy.expiry_date.is_not(None),
            Policy.expiry_date >= today,
            Policy.expiry_date <= horizon,
        )
        .order_by(Policy.expiry_date.asc())
    )
    return list(rows.scalars().all())
