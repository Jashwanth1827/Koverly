"""Document vault endpoints: upload, list, download, delete, processing,
extractions, and signed file access.

Upload returns immediately; processing runs in the background. The file
endpoint requires either an authenticated family member OR a valid signed URL
(minted for a specific document after an authorization check).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from app.api.deps import (
    CurrentUser,
    DbSession,
    FamilyContext,
    FamilyCtx,
    require_role,
)
from app.core.errors import PermissionDeniedError
from app.integrations.storage import get_storage
from app.models.enums import DocumentType, FamilyRole
from app.schemas.common import Message, Page
from app.schemas.document import (
    DocumentOut,
    DocumentUpdate,
    ExtractionConfirm,
    ExtractionOut,
    SignedUrlOut,
)
from app.services import document_service, extraction_service, processing_service

logger = logging.getLogger("koverly.documents.api")

router = APIRouter(tags=["documents"])

WriterCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.MEMBER))]
AdminCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.ADMIN))]


@router.post(
    "/families/{family_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    ctx: WriterCtx,
    db: DbSession,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    policy_id: str | None = Query(default=None),
    claim_id: str | None = Query(default=None),
    document_type: str = Query(default=DocumentType.POLICY.value),
) -> DocumentOut:
    data = await file.read()
    document = await document_service.create_document(
        db,
        family_id=ctx.family_id,
        actor=ctx.user,
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        policy_id=policy_id,
        claim_id=claim_id,
        document_type=document_type,
    )
    # Async processing — never block the upload response.
    background.add_task(processing_service.process_document, document.id)
    return DocumentOut.model_validate(document)


@router.get("/families/{family_id}/documents", response_model=Page[DocumentOut])
async def list_documents(
    ctx: FamilyCtx,
    db: DbSession,
    policy_id: str | None = Query(default=None),
    claim_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[DocumentOut]:
    items, total = await document_service.list_documents(
        db,
        ctx.family_id,
        policy_id=policy_id,
        claim_id=claim_id,
        status=status_filter,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[DocumentOut](
        items=[DocumentOut.model_validate(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/families/{family_id}/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str, ctx: FamilyCtx, db: DbSession
) -> DocumentOut:
    document = await document_service.get_document(db, ctx.family_id, document_id)
    return DocumentOut.model_validate(document)


@router.patch(
    "/families/{family_id}/documents/{document_id}", response_model=DocumentOut
)
async def update_document(
    document_id: str,
    payload: DocumentUpdate,
    ctx: WriterCtx,
    db: DbSession,
) -> DocumentOut:
    document = await document_service.update_document(
        db,
        ctx.family_id,
        document_id,
        policy_id=payload.policy_id,
        document_type=payload.document_type,
        actor=ctx.user,
    )
    return DocumentOut.model_validate(document)


@router.delete(
    "/families/{family_id}/documents/{document_id}", response_model=Message
)
async def delete_document(
    document_id: str, ctx: AdminCtx, db: DbSession
) -> Message:
    await document_service.delete_document(db, ctx.family_id, document_id, ctx.user)
    return Message(message="Document deleted.")


@router.post(
    "/families/{family_id}/documents/{document_id}/reprocess",
    response_model=DocumentOut,
)
async def reprocess_document(
    document_id: str,
    ctx: WriterCtx,
    db: DbSession,
    background: BackgroundTasks,
) -> DocumentOut:
    document = await document_service.get_document(db, ctx.family_id, document_id)
    await processing_service.reprocess_document(db, document)
    background.add_task(processing_service.process_document, document.id)
    return DocumentOut.model_validate(document)


@router.post(
    "/families/{family_id}/documents/{document_id}/signed-url",
    response_model=SignedUrlOut,
)
async def create_signed_url(
    document_id: str, ctx: FamilyCtx, db: DbSession
) -> SignedUrlOut:
    document = await document_service.get_document(db, ctx.family_id, document_id)
    url = document_service.signed_download_url(document)
    return SignedUrlOut(url=url, expires_in=300)


@router.get("/families/{family_id}/documents/{document_id}/download")
async def download_document(
    document_id: str, ctx: FamilyCtx, db: DbSession
) -> Response:
    document, data = await document_service.get_document_bytes(
        db, ctx.family_id, document_id
    )
    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
            "Cache-Control": "no-store",
        },
    )


# --------------------------------------------------------------------------- #
# Signed file endpoint (no bearer auth; HMAC-signed + expiring)
# --------------------------------------------------------------------------- #
@router.get("/documents/file")
async def get_signed_file(
    db: DbSession,
    key: str = Query(...),
    expires: int = Query(...),
    signature: str = Query(...),
) -> Response:
    storage = get_storage()
    if not storage.verify_signed_url(key, expires, signature):
        raise PermissionDeniedError("This link is invalid or has expired.")
    # The key is opaque and only ever issued after authorization, so a valid
    # signature is sufficient here; we still avoid leaking other metadata.
    data = await storage.get(key)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- #
# Extractions (AI-proposed fields requiring user review)
# --------------------------------------------------------------------------- #
@router.get(
    "/families/{family_id}/documents/{document_id}/extractions",
    response_model=list[ExtractionOut],
)
async def list_extractions(
    document_id: str, ctx: FamilyCtx, db: DbSession
) -> list[ExtractionOut]:
    await document_service.get_document(db, ctx.family_id, document_id)
    rows = await processing_service.list_extractions(db, document_id)
    return [ExtractionOut.model_validate(r) for r in rows]


@router.post(
    "/families/{family_id}/documents/{document_id}/extractions/confirm",
    response_model=list[ExtractionOut],
)
async def confirm_extractions(
    document_id: str,
    payload: ExtractionConfirm,
    ctx: WriterCtx,
    db: DbSession,
) -> list[ExtractionOut]:
    rows = await extraction_service.confirm_extractions(
        db,
        family_id=ctx.family_id,
        document_id=document_id,
        payload=payload,
        actor=ctx.user,
    )
    return [ExtractionOut.model_validate(r) for r in rows]
