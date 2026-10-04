"""Document vault service: secure upload, retrieval, and deletion.

Access model: every operation is scoped to a family the caller belongs to.
Files live in private storage and are only ever exposed through short-lived
signed URLs issued after authorization.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.integrations.storage import (
    build_storage_key,
    get_storage,
    sha256_hex,
    sniff_content_type,
)
from app.models.document import Document
from app.models.enums import AuditAction, DocumentStatus, DocumentType
from app.models.policy import Policy
from app.models.user import User
from app.services import audit

logger = logging.getLogger("koverly.documents")


async def create_document(
    db: AsyncSession,
    *,
    family_id: str,
    actor: User,
    filename: str,
    content_type: str,
    data: bytes,
    policy_id: str | None = None,
    claim_id: str | None = None,
    document_type: str = DocumentType.POLICY.value,
) -> Document:
    if not data:
        raise ValidationError("The uploaded file is empty.")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"File exceeds the maximum size of "
            f"{settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    # Verify the real content type from magic bytes (never trust the client).
    detected = sniff_content_type(data, content_type)
    if detected is None or detected not in settings.allowed_upload_types:
        raise ValidationError(
            "Unsupported file type. Allowed types: PDF, JPG, PNG."
        )

    if policy_id is not None:
        policy = await db.get(Policy, policy_id)
        if policy is None or policy.family_id != family_id:
            raise ValidationError("The selected policy does not exist.")

    checksum = sha256_hex(data)
    # Duplicate detection within the family (same bytes already stored).
    duplicate = (
        await db.execute(
            select(Document).where(
                Document.family_id == family_id,
                Document.checksum_sha256 == checksum,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValidationError(
            "This exact document has already been uploaded to this family."
        )

    document = Document(
        family_id=family_id,
        policy_id=policy_id,
        claim_id=claim_id,
        uploaded_by_user_id=actor.id,
        original_filename=filename[:400],
        content_type=detected,
        size_bytes=len(data),
        storage_key="",  # set after id is known
        checksum_sha256=checksum,
        document_type=document_type,
        status=DocumentStatus.UPLOADED.value,
    )
    db.add(document)
    await db.flush()

    key = build_storage_key(family_id, document.id, filename)
    await get_storage().put(key, data, detected)
    document.storage_key = key
    await db.flush()

    await audit.record(
        db,
        action=AuditAction.DOCUMENT_UPLOADED.value,
        resource_type="document",
        resource_id=document.id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={
            "filename": document.original_filename,
            "content_type": detected,
            "size_bytes": len(data),
        },
    )
    await db.commit()
    await db.refresh(document)
    return document


async def get_document(
    db: AsyncSession, family_id: str, document_id: str
) -> Document:
    document = await db.get(Document, document_id)
    if document is None or document.family_id != family_id:
        raise NotFoundError("Document not found.")
    return document


async def list_documents(
    db: AsyncSession,
    family_id: str,
    *,
    policy_id: str | None = None,
    claim_id: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Document], int]:
    stmt = select(Document).where(Document.family_id == family_id)
    count_stmt = select(func.count(Document.id)).where(
        Document.family_id == family_id
    )
    if policy_id:
        stmt = stmt.where(Document.policy_id == policy_id)
        count_stmt = count_stmt.where(Document.policy_id == policy_id)
    if claim_id:
        stmt = stmt.where(Document.claim_id == claim_id)
        count_stmt = count_stmt.where(Document.claim_id == claim_id)
    if status:
        stmt = stmt.where(Document.status == status)
        count_stmt = count_stmt.where(Document.status == status)
    stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    items = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return items, total


async def get_document_bytes(
    db: AsyncSession, family_id: str, document_id: str
) -> tuple[Document, bytes]:
    document = await get_document(db, family_id, document_id)
    data = await get_storage().get(document.storage_key)
    return document, data


def signed_download_url(
    document: Document, *, disposition: str = "inline"
) -> str:
    """Mint a short-lived URL for a document.

    ``disposition`` is ``inline`` for in-app preview or ``attachment`` to
    force a download. The content type is bound into the signature so it
    cannot be tampered with.
    """
    return get_storage().signed_url(
        document.storage_key,
        disposition=disposition,
        content_type=document.content_type,
        filename=document.original_filename,
    )


async def delete_document(
    db: AsyncSession, family_id: str, document_id: str, actor: User
) -> None:
    document = await get_document(db, family_id, document_id)
    key = document.storage_key
    await db.delete(document)
    await db.flush()
    await audit.record(
        db,
        action=AuditAction.DOCUMENT_DELETED.value,
        resource_type="document",
        resource_id=document_id,
        actor_user_id=actor.id,
        family_id=family_id,
        metadata={"filename": document.original_filename},
    )
    await db.commit()
    try:
        await get_storage().delete(key)
    except Exception:  # noqa: BLE001 - DB record already gone; log and continue
        logger.exception("document_storage_delete_failed key=%s", key)


async def update_document(
    db: AsyncSession,
    family_id: str,
    document_id: str,
    *,
    policy_id: str | None,
    document_type: str | None,
    actor: User,
) -> Document:
    document = await get_document(db, family_id, document_id)
    if policy_id is not None:
        policy = await db.get(Policy, policy_id)
        if policy is None or policy.family_id != family_id:
            raise ValidationError("The selected policy does not exist.")
        document.policy_id = policy_id
    if document_type is not None:
        if document_type not in {d.value for d in DocumentType}:
            raise ValidationError("Invalid document type.")
        document.document_type = document_type
    await db.commit()
    await db.refresh(document)
    return document
