"""Extraction review service.

AI-proposed fields must be reviewed by the user before they are treated as
authoritative. This service applies confirmed values onto the linked policy
and marks proposals as confirmed/rejected.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.document import Document, PolicyExtraction
from app.models.enums import AuditAction, ExtractionStatus, PremiumFrequency
from app.models.policy import Policy
from app.models.user import User
from app.schemas.document import ExtractionConfirm
from app.schemas.policy import PolicyCreate
from app.services import audit, policy_service

# Extracted field name -> Policy column. Fields not listed are stored in
# metadata_json (e.g. tpa, waiting_period, deductible).
_COLUMN_MAP = {
    "policy_number": "policy_number",
    "insurer": "insurer",
    "policyholder_name": "policyholder_name",
    "nominee": "nominee",
}
# Numeric columns require coercion; AI output is always text.
_NUMERIC_FIELDS = {"premium", "sum_insured"}
# Date columns require coercion; documents use a variety of date formats.
_DATE_FIELDS = {"start_date", "expiry_date", "renewal_date", "maturity_date"}
# Free-form attributes kept in metadata_json.
_METADATA_FIELDS = {
    "tpa",
    "waiting_period",
    "deductible",
    "claim_contact",
    "premium_frequency",
}
_FREQUENCY_VALUES = {f.value for f in PremiumFrequency}

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d")


async def confirm_extractions(
    db: AsyncSession,
    *,
    family_id: str,
    document_id: str,
    payload: ExtractionConfirm,
    actor: User,
) -> list[PolicyExtraction]:
    document = await db.get(Document, document_id)
    if document is None or document.family_id != family_id:
        raise NotFoundError("Document not found.")

    policy_id = payload.policy_id or document.policy_id
    policy: Policy | None = None
    if policy_id:
        policy = await policy_service.get_policy(db, family_id, policy_id)

    rows = (
        await db.execute(
            select(PolicyExtraction).where(
                PolicyExtraction.document_id == document_id
            )
        )
    ).scalars().all()

    if policy is None and payload.confirm:
        # Nothing to attach the confirmed values to, so create the policy from
        # exactly what the user confirmed. Rejected/absent fields stay empty
        # rather than being filled with guesses.
        policy = await _create_policy_from_confirmed(
            db, family_id=family_id, actor=actor, confirm=payload.confirm
        )
        policy_id = policy.id
        document.policy_id = policy.id

    for row in rows:
        if row.field_name in payload.reject:
            row.status = ExtractionStatus.REJECTED.value
            continue
        if row.field_name in payload.confirm:
            value = payload.confirm[row.field_name]
            _apply_to_policy(policy, row.field_name, value)
            row.value = value
            row.status = ExtractionStatus.CONFIRMED.value
            row.confidence = 1.0

    if policy is not None:
        policy.updated_at = datetime.utcnow()
        if policy_id and document.policy_id != policy_id:
            document.policy_id = policy_id

    await db.flush()
    await audit.record(
        db,
        action=AuditAction.POLICY_UPDATED.value,
        resource_type="document",
        resource_id=document_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={
            "confirmed": sorted(payload.confirm.keys()),
            "rejected": payload.reject,
            "policy_id": policy_id,
        },
    )
    await db.commit()
    return list(
        (
            await db.execute(
                select(PolicyExtraction)
                .where(PolicyExtraction.document_id == document_id)
                .order_by(PolicyExtraction.field_name)
            )
        ).scalars().all()
    )


async def _create_policy_from_confirmed(
    db: AsyncSession, *, family_id: str, actor: User, confirm: dict[str, str]
) -> Policy:
    """Create a policy from user-confirmed extraction values.

    Only the values the user confirmed are used. The policy is created through
    the normal policy service, so audit logging and validation still apply.
    """
    insurer = (confirm.get("insurer") or "").strip()
    policy_number = (confirm.get("policy_number") or "").strip()
    if not insurer or not policy_number:
        raise ValidationError(
            "Confirm an insurer and policy number to create the policy, or add it manually."
        )

    metadata: dict[str, str] = {}
    for key in _METADATA_FIELDS:
        if key == "premium_frequency":
            continue
        if confirm.get(key):
            metadata[key] = confirm[key]

    payload = PolicyCreate(
        family_id=family_id,
        policy_type=_infer_policy_type(confirm),
        insurer=insurer,
        policy_number=policy_number,
        policyholder_name=confirm.get("policyholder_name") or None,
        sum_insured=_coerce_decimal(confirm.get("sum_insured") or ""),
        premium=_coerce_decimal(confirm.get("premium") or ""),
        premium_frequency=_normalize_frequency(confirm.get("premium_frequency")),
        start_date=_coerce_date(confirm.get("start_date") or ""),
        expiry_date=_coerce_date(confirm.get("expiry_date") or ""),
        renewal_date=_coerce_date(confirm.get("renewal_date") or ""),
        maturity_date=_coerce_date(confirm.get("maturity_date") or ""),
        nominee=confirm.get("nominee") or None,
        metadata_json=metadata,
    )
    return await policy_service.create_policy(db, payload, actor)


def _infer_policy_type(confirm: dict[str, str]) -> str:
    """Best-effort policy type from the confirmed field names.

    Health indicators (TPA, waiting period) are the only case inferred from
    metadata; everything else defaults to "other" rather than being guessed.
    """
    if confirm.get("tpa") or confirm.get("waiting_period") or confirm.get("claim_contact"):
        return "health"
    return "other"


def _normalize_frequency(value: str | None) -> PremiumFrequency | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    for candidate in PremiumFrequency:
        if candidate.value == normalized:
            return candidate
    return None


def _apply_to_policy(policy: Policy, field_name: str, value: str) -> None:
    if field_name in _COLUMN_MAP:
        setattr(policy, _COLUMN_MAP[field_name], value)
        return
    if field_name in _NUMERIC_FIELDS:
        coerced = _coerce_decimal(value)
        # An unparseable value must not silently overwrite a numeric column;
        # fall back to preserving it as metadata so nothing is dropped.
        if coerced is not None:
            setattr(policy, field_name, coerced)
            return
    if field_name in _DATE_FIELDS:
        coerced = _coerce_date(value)
        if coerced is not None:
            setattr(policy, field_name, coerced)
            return
    if field_name in _METADATA_FIELDS:
        metadata = dict(policy.metadata_json or {})
        metadata[field_name] = value
        policy.metadata_json = metadata
        return
    # Unknown fields are still preserved as metadata (never dropped silently).
    metadata = dict(policy.metadata_json or {})
    metadata[field_name] = value
    policy.metadata_json = metadata


def _coerce_decimal(value: str) -> Decimal | None:
    """Parse a money string, tolerating currency symbols and thousands separators."""
    cleaned = "".join(ch for ch in value if ch.isdigit() or ch == ".")
    if not cleaned or cleaned.count(".") > 1:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _coerce_date(value: str) -> date | None:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
