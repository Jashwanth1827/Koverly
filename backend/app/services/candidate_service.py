"""Policy candidate review service.

The pipeline proposes one or more policy candidates per document. Nothing is
authoritative until the user confirms it. This service:

* lists the analysis and its candidates for review,
* applies a user-reviewed candidate into a real policy (creating one when the
  candidate is new, updating the linked policy when it already exists),
* records whether each value was AI-extracted, user-confirmed, or user-edited.

It never invents values: only the fields the user confirms are applied, and a
rejected or absent field is left empty rather than guessed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.taxonomy import CATEGORY_TO_POLICY_TYPE, InsuranceCategory, category_for_policy_type
from app.core.errors import NotFoundError, ValidationError
from app.models.document import (
    Document,
    DocumentAnalysis,
    PolicyCandidateField,
    PolicyCandidateRecord,
)
from app.models.enums import AuditAction, ExtractionStatus
from app.models.policy import Policy
from app.models.user import User
from app.schemas.document import CandidateConfirm
from app.schemas.policy import PolicyCreate, PolicyUpdate
from app.services import audit, policy_service
from app.services.extraction_service import (
    _coerce_date,
    _coerce_decimal,
    _normalize_frequency,
)

# Candidate field name -> Policy column.
_COLUMN_MAP = {
    "policy_number": "policy_number",
    "insurer": "insurer",
    "policyholder_name": "policyholder_name",
    "nominee": "nominee",
}
_NUMERIC_FIELDS = {"premium", "sum_insured"}
_DATE_FIELDS = {"start_date", "expiry_date", "renewal_date", "maturity_date"}
# Free-form attributes kept in metadata_json.
_METADATA_FIELDS = {
    "tpa",
    "waiting_period",
    "deductible",
    "claim_contact",
    "premium_frequency",
    "idv",
    "vehicle_registration_number",
    "vehicle_make",
    "vehicle_model",
    "room_rent_limit",
    "co_payment",
    "policy_term",
    "destination",
    "property_address",
}


async def get_analysis(
    db: AsyncSession, family_id: str, document_id: str
) -> tuple[DocumentAnalysis, list[PolicyCandidateRecord]]:
    await _require_document(db, family_id, document_id)
    analysis = (
        await db.execute(
            select(DocumentAnalysis).where(DocumentAnalysis.document_id == document_id)
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise NotFoundError("This document has not been analysed yet.")
    candidates = list(
        (
            await db.execute(
                select(PolicyCandidateRecord)
                .where(PolicyCandidateRecord.document_id == document_id)
                .order_by(PolicyCandidateRecord.candidate_index)
            )
        ).scalars().all()
    )
    return analysis, candidates


async def get_candidate_fields(
    db: AsyncSession, candidate_id: str
) -> list[PolicyCandidateField]:
    rows = await db.execute(
        select(PolicyCandidateField)
        .where(PolicyCandidateField.candidate_id == candidate_id)
        .order_by(PolicyCandidateField.field_name)
    )
    return list(rows.scalars().all())


async def confirm_candidate(
    db: AsyncSession,
    *,
    family_id: str,
    document_id: str,
    candidate_id: str,
    payload: CandidateConfirm,
    actor: User,
) -> tuple[PolicyCandidateRecord, Policy]:
    document = await _require_document(db, family_id, document_id)
    candidate = await db.get(PolicyCandidateRecord, candidate_id)
    if candidate is None or candidate.document_id != document_id:
        raise NotFoundError("Policy candidate not found.")

    field_rows = {f.field_name: f for f in await get_candidate_fields(db, candidate_id)}

    # Merge proposed values with the user's reviewed values. A rejected field is
    # dropped entirely; a field absent from both stays empty.
    values: dict[str, str] = {}
    for name, row in field_rows.items():
        if name in payload.reject:
            continue
        if row.value:
            values[name] = row.value
    for name, value in payload.confirm.items():
        if name in payload.reject:
            continue
        if value is not None and str(value).strip():
            values[name] = str(value).strip()

    if not values.get("insurer") or not values.get("policy_number"):
        raise ValidationError(
            "Confirm an insurer and policy number to save this policy, or add "
            "it manually."
        )

    category = payload.category or candidate.category
    if category not in {c.value for c in InsuranceCategory}:
        category = InsuranceCategory.OTHER.value
    policy_type = CATEGORY_TO_POLICY_TYPE.get(category, "other")

    target_id = payload.policy_id or candidate.policy_id
    policy: Policy | None = None
    if target_id:
        policy = await policy_service.get_policy(db, family_id, target_id)

    metadata = _metadata_from_values(values)

    if policy is None:
        create = PolicyCreate(
            family_id=family_id,
            policy_type=policy_type,
            insurer=values["insurer"],
            policy_number=values["policy_number"],
            policyholder_name=values.get("policyholder_name") or None,
            member_id=payload.member_id,
            sum_insured=_coerce_decimal(values.get("sum_insured") or ""),
            premium=_coerce_decimal(values.get("premium") or ""),
            premium_frequency=_normalize_frequency(values.get("premium_frequency")),
            start_date=_coerce_date(values.get("start_date") or ""),
            expiry_date=_coerce_date(values.get("expiry_date") or ""),
            renewal_date=_coerce_date(values.get("renewal_date") or ""),
            maturity_date=_coerce_date(values.get("maturity_date") or ""),
            nominee=values.get("nominee") or None,
            metadata_json=metadata,
        )
        policy = await policy_service.create_policy(db, create, actor)
    else:
        update = PolicyUpdate(
            policy_type=policy_type,
            insurer=values["insurer"],
            policy_number=values["policy_number"],
            policyholder_name=values.get("policyholder_name") or None,
            member_id=payload.member_id,
            sum_insured=_coerce_decimal(values.get("sum_insured") or ""),
            premium=_coerce_decimal(values.get("premium") or ""),
            premium_frequency=_normalize_frequency(values.get("premium_frequency")),
            start_date=_coerce_date(values.get("start_date") or ""),
            expiry_date=_coerce_date(values.get("expiry_date") or ""),
            renewal_date=_coerce_date(values.get("renewal_date") or ""),
            maturity_date=_coerce_date(values.get("maturity_date") or ""),
            nominee=values.get("nominee") or None,
            metadata_json={**(policy.metadata_json or {}), **metadata},
        )
        policy = await policy_service.update_policy(
            db, family_id, policy.id, update, actor
        )

    # Record review state for every field on the candidate.
    for name, row in field_rows.items():
        if name in payload.reject:
            row.review_status = "rejected"
            continue
        confirmed = payload.confirm.get(name)
        if confirmed is not None and str(confirmed).strip():
            new_value = str(confirmed).strip()
            # Distinguish an edited value from an unchanged confirmation.
            edited = new_value != (row.value or "")
            row.value = new_value
            row.review_status = "user_edited" if edited else "user_confirmed"
            row.confidence = 1.0
        elif row.value:
            row.review_status = "user_confirmed"
            row.confidence = 1.0

    candidate.policy_id = policy.id
    candidate.category = category
    candidate.policy_type = policy_type
    candidate.status = ExtractionStatus.CONFIRMED.value
    candidate.updated_at = datetime.utcnow()

    document.policy_id = document.policy_id or policy.id
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_CREATED.value if target_id is None else AuditAction.POLICY_UPDATED.value,
        resource_type="policy",
        resource_id=policy.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={
            "source": "document_analysis",
            "document_id": document_id,
            "candidate_id": candidate_id,
            "category": category,
        },
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate, policy


async def reject_candidate(
    db: AsyncSession,
    *,
    family_id: str,
    document_id: str,
    candidate_id: str,
    actor: User,
) -> PolicyCandidateRecord:
    await _require_document(db, family_id, document_id)
    candidate = await db.get(PolicyCandidateRecord, candidate_id)
    if candidate is None or candidate.document_id != document_id:
        raise NotFoundError("Policy candidate not found.")
    candidate.status = ExtractionStatus.REJECTED.value
    for row in await get_candidate_fields(db, candidate_id):
        row.review_status = "rejected"
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_UPDATED.value,
        resource_type="document",
        resource_id=document_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"candidate_rejected": candidate_id},
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate


def _metadata_from_values(values: dict[str, str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key in _METADATA_FIELDS:
        if key == "premium_frequency":
            continue
        if values.get(key):
            metadata[key] = values[key]
    return metadata


async def _require_document(
    db: AsyncSession, family_id: str, document_id: str
) -> Document:
    document = await db.get(Document, document_id)
    if document is None or document.family_id != family_id:
        raise NotFoundError("Document not found.")
    return document
