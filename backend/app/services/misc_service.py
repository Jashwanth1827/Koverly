"""Calendar, dashboard, search, emergency, and subscription services."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.security import new_share_token
from app.models.claim import Claim, EmergencyShare, Reminder, Subscription
from app.models.document import Document
from app.models.enums import (
    AuditAction,
    ClaimStatus,
    DocumentStatus,
    PolicyStatus,
    SubscriptionPlan,
)
from app.models.family import Family, FamilyMember
from app.models.policy import Policy
from app.models.user import User
from app.schemas.claim import (
    CalendarEvent,
    DashboardOut,
    EmergencyContact,
    EmergencyPolicy,
    EmergencyProfile,
    FamilyMemberEmergency,
    SearchResult,
)
from app.services import audit, claim_service, intelligence_service, policy_service

logger = logging.getLogger("koverly.misc")


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
async def calendar_events(
    db: AsyncSession,
    family_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[CalendarEvent]:
    start = start or date.today() - timedelta(days=30)
    end = end or date.today() + timedelta(days=365)
    events: list[CalendarEvent] = []

    policies = (
        await db.execute(select(Policy).where(Policy.family_id == family_id))
    ).scalars().all()
    for policy in policies:
        if policy.renewal_date and start <= policy.renewal_date <= end:
            events.append(
                CalendarEvent(
                    id=f"renewal-{policy.id}",
                    kind="renewal",
                    title=f"{policy.insurer} renewal",
                    date=policy.renewal_date,
                    policy_id=policy.id,
                    status=policy.status,
                )
            )
        if policy.expiry_date and start <= policy.expiry_date <= end:
            events.append(
                CalendarEvent(
                    id=f"expiry-{policy.id}",
                    kind="policy",
                    title=f"{policy.insurer} expires",
                    date=policy.expiry_date,
                    policy_id=policy.id,
                    status=policy.status,
                )
            )

    claims = (
        await db.execute(select(Claim).where(Claim.family_id == family_id))
    ).scalars().all()
    for claim in claims:
        if claim.submission_date and start <= claim.submission_date <= end:
            events.append(
                CalendarEvent(
                    id=f"claim-{claim.id}",
                    kind="claim",
                    title=f"{claim.claim_type} claim",
                    date=claim.submission_date,
                    claim_id=claim.id,
                    status=claim.status,
                )
            )

    reminders = (
        await db.execute(select(Reminder).where(Reminder.family_id == family_id))
    ).scalars().all()
    for reminder in reminders:
        if start <= reminder.due_date <= end:
            events.append(
                CalendarEvent(
                    id=f"reminder-{reminder.id}",
                    kind="premium" if reminder.reminder_type == "premium_payment" else "renewal",
                    title=reminder.title,
                    date=reminder.due_date,
                    policy_id=reminder.policy_id,
                    claim_id=reminder.claim_id,
                    status=reminder.status,
                )
            )

    events.sort(key=lambda e: e.date)
    return events


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
async def dashboard(db: AsyncSession, family: Family) -> DashboardOut:
    summary = await policy_service.aggregate_summary(db, family.id)
    intelligence = await intelligence_service.generate(db, family.id)
    recent = await claim_service.recent_claims(db, family.id, limit=5)

    expiring = [i for i in intelligence.items if i.kind == "expiring"]
    actions = [i for i in intelligence.items if i.kind in {"action", "missing_info"}]
    alerts = [i for i in intelligence.items if i.severity == "critical"]

    return DashboardOut(
        family_id=family.id,
        family_name=family.name,
        active_policies=summary["active_policies"],
        total_annual_premium=summary["total_annual_premium"],
        total_life_coverage=summary["total_life_coverage"],
        total_health_coverage=summary["total_health_coverage"],
        total_other_coverage=summary["total_other_coverage"],
        upcoming_renewals=expiring,
        pending_actions=actions,
        recent_claims=recent,
        alerts=alerts,
        by_type=summary["by_type"],
    )


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
async def search(
    db: AsyncSession, family_id: str, query: str, limit: int = 20
) -> list[SearchResult]:
    q = query.strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    results: list[SearchResult] = []

    policies = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family_id,
                or_(
                    func.lower(Policy.insurer).like(like),
                    func.lower(Policy.policy_number).like(like),
                    func.lower(Policy.policyholder_name).like(like),
                    func.lower(Policy.policy_type).like(like),
                ),
            ).limit(limit)
        )
    ).scalars().all()
    for p in policies:
        results.append(
            SearchResult(
                kind="policy",
                id=p.id,
                title=f"{p.insurer} — {p.policy_number}",
                subtitle=f"{p.policy_type} policy",
                policy_id=p.id,
            )
        )

    members = (
        await db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                or_(
                    func.lower(FamilyMember.name).like(like),
                    func.lower(FamilyMember.relationship).like(like),
                ),
            ).limit(limit)
        )
    ).scalars().all()
    for m in members:
        results.append(
            SearchResult(
                kind="family_member", id=m.id, title=m.name, subtitle=m.relationship
            )
        )

    claims = (
        await db.execute(
            select(Claim).where(
                Claim.family_id == family_id,
                or_(
                    func.lower(Claim.claim_type).like(like),
                    func.lower(Claim.provider).like(like),
                    func.lower(Claim.description).like(like),
                ),
            ).limit(limit)
        )
    ).scalars().all()
    for c in claims:
        results.append(
            SearchResult(
                kind="claim",
                id=c.id,
                title=f"{c.claim_type} claim",
                subtitle=c.status,
                policy_id=c.policy_id,
            )
        )

    documents = (
        await db.execute(
            select(Document).where(
                Document.family_id == family_id,
                func.lower(Document.original_filename).like(like),
            ).limit(limit)
        )
    ).scalars().all()
    for d in documents:
        results.append(
            SearchResult(
                kind="document",
                id=d.id,
                title=d.original_filename,
                subtitle=d.document_type,
                policy_id=d.policy_id,
            )
        )

    return results[:limit]


# --------------------------------------------------------------------------- #
# Assistant record lookup
# --------------------------------------------------------------------------- #
# Words that describe a record the family has stored, used to detect
# "find my <thing>" style questions. Kept narrow so ordinary policy questions
# ("what does my health policy cover?") are not mistaken for record lookups.
_RECORD_LOOKUP_NOUNS = (
    "policy number",
    "policy no",
    "policy",
    "claim",
    "document",
    "file",
    "receipt",
    "invoice",
)

_LOOKUP_MARKERS = (
    "find",
    "search",
    "look up",
    "lookup",
    "locate",
    "where is",
    "where's",
    "show me",
    "show",
)

# Tokens that carry no identifying value on their own. If stripping the lookup
# phrasing leaves only these, the question is aggregate ("show me all my
# claims") or a coverage question ("which policy covers hospitalisation")
# rather than a lookup, so we defer to the aggregate/document tools.
_LOOKUP_STOPWORDS = {
    "all",
    "any",
    "everything",
    "every",
    "list",
    "the",
    "my",
    "our",
    "me",
    "us",
    "please",
    "for",
    "about",
    "of",
    "to",
    "on",
    "in",
    "current",
    "active",
    "recorded",
    "existing",
    "available",
    "latest",
    "recent",
    "new",
    "and",
    "or",
    "which",
    "what",
    "how",
    "when",
    "where",
    "who",
    "does",
    "do",
    "is",
    "are",
    "can",
    "could",
    "tell",
    "explain",
    "give",
    "need",
    "want",
    "cover",
    "covers",
    "covered",
}

# Pattern for an explicit identifier: "policy number POL-123", "policy no
# POL-123", "policy #POL-123". Requires the number/no/# keyword so ordinary
# "my health policy covers..." phrasing is not captured.
_POLICY_NUMBER_RE = re.compile(
    r"(?:policy\s*(?:number|no\.?|#))\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,})",
    re.IGNORECASE,
)
# Implicit identifier: "policy POL-123" where the token itself contains a digit.
_POLICY_ID_RE = re.compile(
    r"policy\s*[:#]?\s*([A-Za-z0-9\-/]*\d[A-Za-z0-9\-/]*)",
    re.IGNORECASE,
)


def record_lookup_term(question: str) -> str | None:
    """Return the record identifier to search for, or None.

    Detects explicit record-lookup questions and extracts a focused search
    term. To avoid hijacking ordinary coverage questions, a lookup requires a
    concrete anchor: an explicit policy number, or a distinctive term
    (capitalised name / token containing a digit). Returns None otherwise, so
    the assistant falls through to document-grounded answering.
    """
    q = question.strip()
    lowered = q.lower()
    if not any(marker in lowered for marker in _LOOKUP_MARKERS):
        return None
    if not any(noun in lowered for noun in _RECORD_LOOKUP_NOUNS):
        return None

    # 1) An explicit policy number is the strongest anchor.
    match = _POLICY_NUMBER_RE.search(q) or _POLICY_ID_RE.search(q)
    if match:
        return match.group(1)

    # 2) Otherwise strip lookup phrasing and record nouns, then keep only
    #    distinctive tokens (capitalised in the original, or containing a
    #    digit). "find my claim for City Hospital" -> "City Hospital".
    cleaned = q
    for phrase in (
        "can you",
        "please",
        "find",
        "search for",
        "search",
        "look up",
        "lookup",
        "locate",
        "where is",
        "where's",
        "show me",
        "show",
        "for me",
    ):
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:policy|claim|document|file|receipt|invoice)s?\b", " ", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"[^\w\s\-/]", " ", cleaned)
    distinctive = [
        t
        for t in cleaned.split()
        if t.lower() not in _LOOKUP_STOPWORDS
        and (t[:1].isupper() or any(ch.isdigit() for ch in t))
    ]
    if not distinctive:
        return None
    term = " ".join(distinctive)
    if len(term) < 3:
        return None
    return term


# --------------------------------------------------------------------------- #
# Emergency mode
# --------------------------------------------------------------------------- #
_CLAIM_INSTRUCTIONS = [
    "Contact the insurer or TPA helpline listed on the policy before treatment "
    "where possible, and inform them of the hospital admission.",
    "For cashless admission, present the health card and policy number at the "
    "hospital insurance desk.",
    "For reimbursement, keep original bills, discharge summary, prescriptions, "
    "and payment receipts.",
    "Notify the insurer within the timeframe stated in the policy.",
]


async def emergency_profile(
    db: AsyncSession, family: Family, member_id: str | None = None
) -> EmergencyProfile:
    members = (
        await db.execute(
            select(FamilyMember).where(FamilyMember.family_id == family.id)
        )
    ).scalars().all()

    selected: FamilyMember | None = None
    if member_id:
        selected = next((m for m in members if m.id == member_id), None)
        if selected is None:
            raise NotFoundError("Family member not found.")

    policies = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family.id,
                Policy.status == PolicyStatus.ACTIVE.value,
            )
        )
    ).scalars().all()

    relevant = []
    for policy in policies:
        if policy.policy_type not in {"health", "personal_accident", "life"}:
            continue
        if selected and policy.member_id and policy.member_id != selected.id:
            continue
        doc_ids = [
            d.id
            for d in (
                await db.execute(
                    select(Document).where(Document.policy_id == policy.id)
                )
            ).scalars().all()
        ]
        meta = policy.metadata_json or {}
        relevant.append(
            EmergencyPolicy(
                policy_id=policy.id,
                policy_type=policy.policy_type,
                insurer=policy.insurer,
                policy_number=policy.policy_number,
                sum_insured=policy.sum_insured,
                tpa=meta.get("tpa"),
                claim_contact=meta.get("claim_contact"),
                expiry_date=policy.expiry_date,
                document_ids=doc_ids,
            )
        )

    contacts: list[EmergencyContact] = []
    if selected:
        if selected.phone:
            contacts.append(EmergencyContact(label="Member phone", value=selected.phone))
        if selected.blood_group:
            contacts.append(
                EmergencyContact(label="Blood group", value=selected.blood_group)
            )
    for policy in relevant:
        if policy.tpa:
            contacts.append(
                EmergencyContact(label=f"{policy.insurer} TPA", value=policy.tpa)
            )
        if policy.claim_contact:
            contacts.append(
                EmergencyContact(
                    label=f"{policy.insurer} claim helpline",
                    value=policy.claim_contact,
                )
            )

    return EmergencyProfile(
        family_id=family.id,
        family_name=family.name,
        generated_at=datetime.now(timezone.utc),
        member=(
            FamilyMemberEmergency(
                id=selected.id,
                name=selected.name,
                relationship=selected.relationship,
                blood_group=selected.blood_group,
                date_of_birth=selected.date_of_birth,
            )
            if selected
            else None
        ),
        policies=relevant,
        contacts=contacts,
        claim_instructions=_CLAIM_INSTRUCTIONS,
    )


async def create_emergency_share(
    db: AsyncSession,
    family: Family,
    actor: User,
    *,
    member_id: str | None,
    ttl_minutes: int,
    max_views: int,
) -> EmergencyShare:
    if member_id:
        member = await db.get(FamilyMember, member_id)
        if member is None or member.family_id != family.id:
            raise ValidationError("The selected family member does not exist.")
    share = EmergencyShare(
        family_id=family.id,
        created_by_user_id=actor.id,
        token=new_share_token(),
        member_id=member_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        max_views=max_views,
    )
    db.add(share)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.EMERGENCY_SHARE_CREATED.value,
        resource_type="emergency_share",
        resource_id=share.id,
        actor_user_id=actor.id,
        family_id=family.id,
        metadata={"ttl_minutes": ttl_minutes, "member_id": member_id},
    )
    await db.commit()
    await db.refresh(share)
    return share


async def revoke_emergency_share(
    db: AsyncSession, family: Family, share_id: str, actor: User
) -> None:
    share = await db.get(EmergencyShare, share_id)
    if share is None or share.family_id != family.id:
        raise NotFoundError("Share link not found.")
    share.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.EMERGENCY_SHARE_REVOKED.value,
        resource_type="emergency_share",
        resource_id=share.id,
        actor_user_id=actor.id,
        family_id=family.id,
    )
    await db.commit()


async def resolve_emergency_share(
    db: AsyncSession, token: str
) -> EmergencyProfile:
    """Public resolver for a share token. No authentication required, but the
    payload is limited to the curated emergency summary."""
    share = (
        await db.execute(
            select(EmergencyShare).where(EmergencyShare.token == token)
        )
    ).scalar_one_or_none()
    if share is None:
        raise NotFoundError("This link is not valid.")
    now = datetime.now(timezone.utc)
    expires = share.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if share.revoked_at is not None:
        raise NotFoundError("This link has been revoked.")
    if expires < now:
        raise NotFoundError("This link has expired.")
    if share.view_count >= share.max_views:
        raise NotFoundError("This link has reached its view limit.")

    family = await db.get(Family, share.family_id)
    if family is None:
        raise NotFoundError("This link is not valid.")

    share.view_count += 1
    await db.commit()
    return await emergency_profile(db, family, share.member_id)


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
async def get_or_create_subscription(
    db: AsyncSession, family_id: str
) -> Subscription:
    subscription = (
        await db.execute(
            select(Subscription).where(Subscription.family_id == family_id)
        )
    ).scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(
            family_id=family_id, plan=SubscriptionPlan.FREE.value, status="active"
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
    return subscription


async def set_subscription_plan(
    db: AsyncSession, family_id: str, plan: SubscriptionPlan, actor: User
) -> Subscription:
    """Admin-only plan change. No payment is processed; this only records the
    intended plan so billing can be wired in later."""
    subscription = await get_or_create_subscription(db, family_id)
    subscription.plan = plan.value
    await db.commit()
    await db.refresh(subscription)
    return subscription
