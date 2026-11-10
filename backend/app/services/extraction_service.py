"""Extraction review service.

AI-proposed fields must be reviewed by the user before they are treated as
authoritative. This service applies confirmed values onto the linked policy
and marks proposals as confirmed/rejected.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_ai_provider
from app.core.errors import NotFoundError, ValidationError
from app.models.document import Document, PolicyExtraction
from app.models.enums import AuditAction, ExtractionStatus, PolicyType
from app.models.policy import Policy
from app.models.user import User
from app.schemas.document import ExtractionConfirm
from app.schemas.policy import PolicyCreate
from app.services import audit, policy_service

logger = logging.getLogger("koverly.extraction")

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

    confirmed_values = {
        name: value for name, value in payload.confirm.items() if value.strip()
    }

    created_policy = False
    if policy is None and payload.create_policy and confirmed_values:
        policy, created_policy = await _create_policy_from_confirmed(
            db,
            family_id=family_id,
            document=document,
            payload=payload,
            values=confirmed_values,
            actor=actor,
        )
        policy_id = policy.id
        document.policy_id = policy.id

    if policy is None and confirmed_values:
        raise ValidationError(
            "Choose an existing policy or create a new one before submitting."
        )

    rows = (
        await db.execute(
            select(PolicyExtraction).where(
                PolicyExtraction.document_id == document_id
            )
        )
    ).scalars().all()

    for row in rows:
        if row.field_name in payload.reject:
            row.status = ExtractionStatus.REJECTED.value
            continue
        if row.field_name in payload.confirm:
            value = payload.confirm[row.field_name]
            # An empty value means the user cleared/ignored the field.
            if not value.strip():
                row.status = ExtractionStatus.REJECTED.value
                continue
            if policy is None:  # pragma: no cover - guarded above
                raise ValidationError(
                    "Choose an existing policy or create a new one before "
                    "submitting."
                )
            _apply_to_policy(policy, row.field_name, value)
            row.value = value
            row.policy_id = policy.id
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
            "confirmed": sorted(confirmed_values.keys()),
            "rejected": payload.reject,
            "policy_id": policy_id,
            "created_policy": created_policy,
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


async def _infer_policy_type(document: Document) -> PolicyType:
    """Best-effort classification from the document text.

    Falls back to ``other`` when the provider cannot classify; the type is
    only a convenience and never overrides a user's explicit choice.
    """
    text = (document.extracted_text or "")[:40000]
    if not text.strip():
        return PolicyType.OTHER
    try:
        predicted = await get_ai_provider().classify_document(text)
        return PolicyType(predicted)
    except Exception:  # noqa: BLE001 - classification is optional
        logger.warning("policy_type_inference_failed document_id=%s", document.id)
        return PolicyType.OTHER


async def _create_policy_from_confirmed(
    db: AsyncSession,
    *,
    family_id: str,
    document: Document,
    payload: ExtractionConfirm,
    values: dict[str, str],
    actor: User,
) -> tuple[Policy, bool]:
    """Create a policy from reviewed extraction values.

    A policy with the same number and insurer is reused instead of creating a
    duplicate. The caller then applies the confirmed values to it. Returns the
    policy and whether it was newly created.
    """
    insurer = values.get("insurer", "").strip()
    policy_number = values.get("policy_number", "").strip()
    missing = []
    if not insurer:
        missing.append("insurer")
    if not policy_number:
        missing.append("policy number")
    if missing:
        raise ValidationError(
            f"Enter the {' and '.join(missing)} before creating a policy."
        )

    existing = (
        await db.execute(
            select(Policy).where(
                Policy.family_id == family_id,
                func.lower(Policy.policy_number) == policy_number.lower(),
                func.lower(Policy.insurer) == insurer.lower(),
            )
        )
    ).scalars().first()
    if existing is not None:
        logger.info(
            "extraction_matched_existing_policy",
            extra={"extra_fields": {"policy_id": existing.id}},
        )
        return existing, False

    policy_type = payload.policy_type or await _infer_policy_type(document)
    metadata: dict[str, str] = {}
    columns: dict[str, object] = {}
    for name, value in values.items():
        if name in {"insurer", "policy_number"}:
            continue
        if name in _COLUMN_MAP:
            columns[_COLUMN_MAP[name]] = value
        elif name in _NUMERIC_FIELDS:
            coerced = _coerce_decimal(value)
            if coerced is not None:
                columns[name] = coerced
            else:
                metadata[name] = value
        elif name in _DATE_FIELDS:
            coerced_date = _coerce_date(value)
            if coerced_date is not None:
                columns[name] = coerced_date
            else:
                metadata[name] = value
        else:
            metadata[name] = value

    create = PolicyCreate(
        family_id=family_id,
        policy_type=policy_type,
        insurer=insurer,
        policy_number=policy_number,
        metadata_json=metadata,
        **columns,
    )
    return await policy_service.create_policy(db, create, actor), True


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
