"""Insurance intelligence: expiry detection, missing information, potential
overlap detection, and coverage map generation.

All findings are derived from recorded data. Overlaps are phrased as
"potential" and no financial advice is produced.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import PolicyExtraction
from app.models.enums import ExtractionStatus, PolicyStatus, PolicyType
from app.models.family import FamilyMember
from app.models.policy import Policy
from app.schemas.claim import (
    CoverageMap,
    CoverageNode,
    IntelligenceItem,
    IntelligenceResponse,
)

RENEWAL_WINDOW_DAYS = 60


def _today() -> date:
    return date.today()


async def _family_policies(db: AsyncSession, family_id: str) -> list[Policy]:
    rows = await db.execute(select(Policy).where(Policy.family_id == family_id))
    return list(rows.scalars().all())


async def _family_members(db: AsyncSession, family_id: str) -> list[FamilyMember]:
    rows = await db.execute(
        select(FamilyMember).where(FamilyMember.family_id == family_id)
    )
    return list(rows.scalars().all())


async def _unconfirmed_extractions(
    db: AsyncSession, family_id: str
) -> list[PolicyExtraction]:
    rows = await db.execute(
        select(PolicyExtraction).where(
            PolicyExtraction.family_id == family_id,
            PolicyExtraction.status == ExtractionStatus.PROPOSED.value,
        )
    )
    return list(rows.scalars().all())


def _expiry_items(policies: list[Policy]) -> list[IntelligenceItem]:
    items: list[IntelligenceItem] = []
    today = _today()
    for policy in policies:
        if policy.status != PolicyStatus.ACTIVE.value:
            continue
        target = policy.renewal_date or policy.expiry_date
        if target is None:
            continue
        days = (target - today).days
        if days < 0:
            items.append(
                IntelligenceItem(
                    kind="expiring",
                    severity="critical",
                    title=f"{policy.insurer} {policy.policy_type} has expired",
                    detail=f"This policy expired on {target.isoformat()}.",
                    policy_id=policy.id,
                    due_date=target,
                )
            )
        elif days <= RENEWAL_WINDOW_DAYS:
            severity = "critical" if days <= 14 else "warning"
            items.append(
                IntelligenceItem(
                    kind="expiring",
                    severity=severity,
                    title=f"{policy.insurer} {policy.policy_type} renewal due",
                    detail=f"Renewal in {days} day(s) on {target.isoformat()}.",
                    policy_id=policy.id,
                    due_date=target,
                )
            )
    return items


def _missing_info_items(
    policies: list[Policy], members: list[FamilyMember]
) -> list[IntelligenceItem]:
    items: list[IntelligenceItem] = []
    for policy in policies:
        if policy.policy_type == PolicyType.LIFE.value and not policy.nominee:
            items.append(
                IntelligenceItem(
                    kind="missing_info",
                    severity="warning",
                    title="Nominee not recorded",
                    detail=f"No nominee is recorded for the {policy.insurer} life "
                    f"policy ({policy.policy_number}).",
                    policy_id=policy.id,
                )
            )
        if policy.sum_insured is None:
            items.append(
                IntelligenceItem(
                    kind="missing_info",
                    severity="info",
                    title="Sum insured not recorded",
                    detail=f"The sum insured is missing for {policy.insurer} "
                    f"({policy.policy_number}).",
                    policy_id=policy.id,
                )
            )
        if policy.expiry_date is None and policy.renewal_date is None:
            items.append(
                IntelligenceItem(
                    kind="missing_info",
                    severity="info",
                    title="Expiry date not recorded",
                    detail=f"No expiry or renewal date is recorded for "
                    f"{policy.insurer} ({policy.policy_number}).",
                    policy_id=policy.id,
                )
            )
    for member in members:
        if member.relationship == "self":
            continue
        # Dependants with no policies at all are worth surfacing.
        has_policy = any(p.member_id == member.id for p in policies)
        if not has_policy:
            items.append(
                IntelligenceItem(
                    kind="missing_info",
                    severity="info",
                    title=f"No policies for {member.name}",
                    detail=f"{member.name} ({member.relationship}) has no policies "
                    f"recorded in this family.",
                    member_id=member.id,
                )
            )
    return items


def _overlap_items(policies: list[Policy]) -> list[IntelligenceItem]:
    """Detect multiple policies of the same type covering the family.

    Phrased cautiously as a potential overlap — never as advice.
    """
    items: list[IntelligenceItem] = []
    by_type: dict[str, list[Policy]] = {}
    for policy in policies:
        if policy.status != PolicyStatus.ACTIVE.value:
            continue
        by_type.setdefault(policy.policy_type, []).append(policy)

    for ptype, group in by_type.items():
        if ptype in {PolicyType.LIFE.value, PolicyType.HEALTH.value, PolicyType.PERSONAL_ACCIDENT.value} and len(group) > 1:
            items.append(
                IntelligenceItem(
                    kind="potential_overlap",
                    severity="info",
                    title=f"Potential overlap: {ptype.replace('_', ' ')} coverage",
                    detail=(
                        f"{ptype.replace('_', ' ').title()} coverage appears across "
                        f"{len(group)} recorded policies. This may be intentional; "
                        f"review to confirm the coverage is not duplicated."
                    ),
                )
            )
    return items


async def generate(
    db: AsyncSession, family_id: str
) -> IntelligenceResponse:
    policies = await _family_policies(db, family_id)
    members = await _family_members(db, family_id)

    items: list[IntelligenceItem] = []
    items.extend(_expiry_items(policies))
    items.extend(_missing_info_items(policies, members))
    items.extend(_overlap_items(policies))

    # Unconfirmed AI extractions require review (pending action).
    for extraction in await _unconfirmed_extractions(db, family_id):
        if extraction.found:
            items.append(
                IntelligenceItem(
                    kind="action",
                    severity="info",
                    title="Review AI-extracted information",
                    detail=f"The field “{extraction.field_name}” was extracted from "
                    f"a document and needs your confirmation.",
                    policy_id=extraction.policy_id,
                )
            )
            break  # one aggregate prompt is enough

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: severity_order.get(i.severity, 3))

    return IntelligenceResponse(
        family_id=family_id,
        generated_at=datetime.now(timezone.utc),
        items=items,
    )


async def coverage_map(db: AsyncSession, family_id: str) -> CoverageMap:
    policies = await _family_policies(db, family_id)
    members = await _family_members(db, family_id)
    member_names = {m.id: m.name for m in members}

    categories: list[CoverageNode] = []
    for ptype in PolicyType:
        group = [
            p
            for p in policies
            if p.policy_type == ptype.value and p.status == PolicyStatus.ACTIVE.value
        ]
        total = sum((Decimal(p.sum_insured or 0) for p in group), Decimal(0))
        expiries = [p.expiry_date for p in group if p.expiry_date]
        holders = sorted(
            {
                (member_names.get(p.member_id) or p.policyholder_name or "Unassigned")
                for p in group
            }
        )
        missing: list[str] = []
        attention: list[str] = []
        for p in group:
            if p.sum_insured is None:
                missing.append(f"{p.insurer}: sum insured not recorded")
            if p.policy_type == PolicyType.LIFE.value and not p.nominee:
                missing.append(f"{p.insurer}: nominee not recorded")
            if p.expiry_date:
                days = (p.expiry_date - _today()).days
                if 0 <= days <= RENEWAL_WINDOW_DAYS:
                    attention.append(f"{p.insurer}: renews in {days} day(s)")
        categories.append(
            CoverageNode(
                category=ptype.value,
                policy_count=len(group),
                total_coverage=total,
                policyholders=holders,
                nearest_expiry=min(expiries) if expiries else None,
                missing_info=missing,
                attention=attention,
            )
        )

    return CoverageMap(family_id=family_id, categories=categories)
