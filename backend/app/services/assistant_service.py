"""AI assistant service ("Ask Koverly").

Uses tool/function-based retrieval rather than dumping the database into a
prompt. The router inspects the question and calls narrowly scoped,
family-authorized tools that return compact structured facts. Document-grounded
questions use the RAG retrieval service.

Nothing is fabricated: when no grounded content is found, the canonical
not-found message is returned with ``grounded=False``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import NOT_FOUND_MESSAGE, AnswerResult, RecordMatch, SourceRef
from app.ai.factory import get_ai_provider
from app.models.claim import Claim
from app.models.enums import ClaimStatus, PolicyStatus, PolicyType
from app.models.family import FamilyMember
from app.models.policy import Policy
from app.services import misc_service, policy_service, retrieval_service

logger = logging.getLogger("koverly.assistant")

DISCLAIMER = (
    "This is an informational summary of your uploaded documents, not "
    "insurance, legal, medical, or financial advice."
)


@dataclass
class ToolResult:
    text: str
    data: dict = field(default_factory=dict)


async def _tool_policy_summary(db: AsyncSession, family_id: str) -> ToolResult:
    summary = await policy_service.aggregate_summary(db, family_id)
    text = (
        f"You have {summary['active_policies']} active policies. "
        f"Total annual premium: {summary['total_annual_premium']}. "
        f"Life coverage: {summary['total_life_coverage']}. "
        f"Health coverage: {summary['total_health_coverage']}."
    )
    return ToolResult(text=text, data=summary)


async def _tool_policies_by_member(
    db: AsyncSession, family_id: str, member_name: str
) -> ToolResult:
    member = (
        await db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.name.ilike(f"%{member_name}%"),
            )
        )
    ).scalars().first()
    if member is None:
        return ToolResult(text=f"No family member matching “{member_name}” was found.")
    policies = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family_id, Policy.member_id == member.id
            )
        )
    ).scalars().all()
    if not policies:
        return ToolResult(
            text=f"No policies are recorded for {member.name}.",
            data={"member_id": member.id, "policies": []},
        )
    lines = [
        f"{p.insurer} {p.policy_type} policy {p.policy_number}"
        + (f" (expires {p.expiry_date})" if p.expiry_date else "")
        for p in policies
    ]
    return ToolResult(
        text=f"{member.name} has {len(policies)} recorded policies: " + "; ".join(lines),
        data={"member_id": member.id, "count": len(policies)},
    )


async def _tool_expiring(db: AsyncSession, family_id: str, days: int = 365) -> ToolResult:
    policies = await policy_service.policies_expiring_within(db, family_id, days)
    if not policies:
        return ToolResult(text=f"No policies expire within the next {days} days.")
    lines = [
        f"{p.insurer} {p.policy_type} ({p.policy_number}) expires {p.expiry_date}"
        for p in policies
    ]
    return ToolResult(
        text=f"{len(policies)} policies expire within {days} days: " + "; ".join(lines),
        data={"count": len(policies)},
    )


async def _tool_claims(db: AsyncSession, family_id: str) -> ToolResult:
    open_statuses = {
        ClaimStatus.SUBMITTED.value,
        ClaimStatus.DOCUMENTS_REQUIRED.value,
        ClaimStatus.UNDER_REVIEW.value,
    }
    claims = (
        await db.execute(
            select(Claim).where(
                Claim.family_id == family_id, Claim.status.in_(open_statuses)
            )
        )
    ).scalars().all()
    if not claims:
        return ToolResult(text="There are no active claims.")
    lines = [f"{c.claim_type} claim ({c.status})" for c in claims]
    return ToolResult(
        text=f"You have {len(claims)} active claims: " + "; ".join(lines),
        data={"count": len(claims)},
    )


async def _tool_coverage_by_type(
    db: AsyncSession, family_id: str, policy_type: str
) -> ToolResult:
    policies = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family_id,
                Policy.policy_type == policy_type,
                Policy.status == PolicyStatus.ACTIVE.value,
            )
        )
    ).scalars().all()
    if not policies:
        return ToolResult(text=f"No active {policy_type} policies are recorded.")
    total = sum((Decimal(p.sum_insured or 0) for p in policies), Decimal(0))
    return ToolResult(
        text=f"You have {len(policies)} active {policy_type} policies with total "
        f"sum insured {total}.",
        data={"count": len(policies), "total": str(total)},
    )


async def _tool_waiting_periods(db: AsyncSession, family_id: str) -> ToolResult:
    policies = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family_id,
                Policy.policy_type == PolicyType.HEALTH.value,
            )
        )
    ).scalars().all()
    lines = []
    for p in policies:
        wp = (p.metadata_json or {}).get("waiting_period")
        if wp:
            lines.append(f"{p.insurer} ({p.policy_number}): waiting period {wp}")
    if not lines:
        return ToolResult(
            text="No waiting periods are recorded. Upload the full policy "
            "document to extract waiting periods."
        )
    return ToolResult(text="; ".join(lines))


async def _tool_search_records(
    db: AsyncSession, family_id: str, term: str
) -> ToolResult:
    """Search the family's stored records (policies, members, claims, docs).

    Delegates to the same family-scoped search used by the search page, so the
    assistant can only ever surface records the caller is authorized to see.
    """
    results = await misc_service.search(db, family_id, term, limit=8)
    if not results:
        return ToolResult(text="", data={"matches": [], "term": term})
    matches = [
        RecordMatch(
            kind=r.kind, id=r.id, title=r.title, subtitle=r.subtitle
        )
        for r in results
    ]
    labels = {
        "policy": "policy",
        "family_member": "family member",
        "claim": "claim",
        "document": "document",
    }
    lines = [f"{labels.get(m.kind, m.kind)}: {m.title}" for m in matches]
    return ToolResult(
        text=f"I found {len(matches)} matching records: " + "; ".join(lines),
        data={"matches": matches, "term": term},
    )


_KEYWORD_ROUTES = [
    (("how much", "total", "summary", "overview", "how many"), _tool_policy_summary),
    (("expire", "expiry", "expiring", "renew"), _tool_expiring),
    (("claim", "claims"), _tool_claims),
    (("waiting period",), _tool_waiting_periods),
]

_TYPE_KEYWORDS = {
    "health": PolicyType.HEALTH.value,
    "life": PolicyType.LIFE.value,
    "motor": PolicyType.MOTOR.value,
    "car": PolicyType.MOTOR.value,
    "home": PolicyType.HOME.value,
    "travel": PolicyType.TRAVEL.value,
    "accident": PolicyType.PERSONAL_ACCIDENT.value,
}


async def answer(
    db: AsyncSession,
    *,
    family_id: str,
    question: str,
    policy_id: str | None = None,
    top_k: int = 5,
) -> AnswerResult:
    q = question.lower().strip()

    # 0) Explicit record-lookup questions ("find my claim for City Hospital",
    #    "where is policy number POL-123"). These use the same family-scoped
    #    search as the search page, so no cross-tenant records can surface.
    matches: list[RecordMatch] = []
    lookup_term = misc_service.record_lookup_term(question)
    if lookup_term is not None:
        search_result = await _tool_search_records(db, family_id, lookup_term)
        matches = search_result.data.get("matches", [])
        provider = get_ai_provider()
        if matches:
            return AnswerResult(
                answer=search_result.text,
                sources=[],
                grounded=True,  # grounded in the user's own stored records
                provider=provider.name,
                disclaimer=DISCLAIMER,
                matches=matches,
            )
        return AnswerResult(
            answer=(
                f"I couldn't find any records matching “{lookup_term}” in your "
                "family's policies, claims, documents, or members."
            ),
            sources=[],
            grounded=False,
            provider=provider.name,
            disclaimer=DISCLAIMER,
            matches=[],
        )

    # 1) Document-grounded retrieval first — it is the most authoritative
    #    source for "what does this policy cover / exclude" style questions.
    contexts = await retrieval_service.retrieve(
        db, family_id=family_id, query=question, top_k=top_k, policy_id=policy_id
    )

    # 2) Structured tool routing for aggregate/relational questions.
    tool_text: str | None = None
    for keywords, tool in _KEYWORD_ROUTES:
        if any(k in q for k in keywords):
            result = await tool(db, family_id)
            tool_text = result.text
            break

    if tool_text is None:
        for word, ptype in _TYPE_KEYWORDS.items():
            if word in q:
                result = await _tool_coverage_by_type(db, family_id, ptype)
                tool_text = result.text
                break

    # 3) "What does <person> have?" style questions.
    if tool_text is None and ("father" in q or "mother" in q or "spouse" in q or "wife" in q or "husband" in q):
        for name in ("father", "mother", "spouse", "wife", "husband"):
            if name in q:
                result = await _tool_policies_by_member(db, family_id, name)
                tool_text = result.text
                break

    provider = get_ai_provider()

    if contexts:
        result = await provider.answer_question(question, contexts)
        if result.grounded:
            # Combine grounded document answer with any structured tool fact.
            if tool_text:
                result.answer = f"{result.answer}\n\nRecorded policies: {tool_text}"
            result.disclaimer = DISCLAIMER
            return result

    if tool_text:
        return AnswerResult(
            answer=tool_text,
            sources=[],
            grounded=True,  # grounded in the user's own structured records
            provider=provider.name,
            disclaimer=DISCLAIMER,
        )

    return AnswerResult(
        answer=NOT_FOUND_MESSAGE,
        sources=[],
        grounded=False,
        provider=provider.name,
        disclaimer=DISCLAIMER,
    )
