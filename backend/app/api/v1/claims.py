"""Claim endpoints — CRUD, timeline, and claim documents."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import DbSession, FamilyContext, FamilyCtx, require_role
from app.models.enums import DocumentType, FamilyRole
from app.schemas.claim import ClaimCreate, ClaimDetail, ClaimOut, ClaimUpdate
from app.schemas.common import Message, Page
from app.schemas.document import DocumentOut
from app.services import claim_service, document_service

router = APIRouter(prefix="/families/{family_id}/claims", tags=["claims"])

WriterCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.MEMBER))]
AdminCtx = Annotated[FamilyContext, Depends(require_role(FamilyRole.ADMIN))]


@router.post("", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
async def create_claim(
    payload: ClaimCreate, ctx: WriterCtx, db: DbSession
) -> ClaimOut:
    payload.family_id = ctx.family_id
    claim = await claim_service.create_claim(db, payload, ctx.user)
    return ClaimOut.model_validate(claim)


@router.get("", response_model=Page[ClaimOut])
async def list_claims(
    ctx: FamilyCtx,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    policy_id: str | None = Query(default=None),
    member_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> Page[ClaimOut]:
    items, total = await claim_service.list_claims(
        db,
        ctx.family_id,
        status=status_filter,
        policy_id=policy_id,
        member_id=member_id,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[ClaimOut](
        items=[ClaimOut.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{claim_id}", response_model=ClaimDetail)
async def get_claim(
    claim_id: str, ctx: FamilyCtx, db: DbSession
) -> ClaimDetail:
    claim = await claim_service.get_claim_detail(db, ctx.family_id, claim_id)
    return ClaimDetail.model_validate(claim)


@router.patch("/{claim_id}", response_model=ClaimOut)
async def update_claim(
    claim_id: str, payload: ClaimUpdate, ctx: WriterCtx, db: DbSession
) -> ClaimOut:
    claim = await claim_service.update_claim(
        db, ctx.family_id, claim_id, payload, ctx.user
    )
    return ClaimOut.model_validate(claim)


@router.delete("/{claim_id}", response_model=Message)
async def delete_claim(
    claim_id: str, ctx: AdminCtx, db: DbSession
) -> Message:
    await claim_service.delete_claim(db, ctx.family_id, claim_id, ctx.user)
    return Message(message="Claim deleted.")


@router.get("/{claim_id}/documents", response_model=list[DocumentOut])
async def list_claim_documents(
    claim_id: str, ctx: FamilyCtx, db: DbSession
) -> list[DocumentOut]:
    await claim_service.get_claim(db, ctx.family_id, claim_id)
    items, _ = await document_service.list_documents(
        db, ctx.family_id, claim_id=claim_id, limit=100
    )
    return [DocumentOut.model_validate(d) for d in items]


@router.post(
    "/{claim_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_claim_document(
    claim_id: str,
    ctx: WriterCtx,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    await claim_service.get_claim(db, ctx.family_id, claim_id)
    data = await file.read()
    document = await document_service.create_document(
        db,
        family_id=ctx.family_id,
        actor=ctx.user,
        filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        claim_id=claim_id,
        document_type=DocumentType.CLAIM.value,
    )
    return DocumentOut.model_validate(document)
