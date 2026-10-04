"""Document processing pipeline.

Runs asynchronously after upload::

    document -> format detection -> text extraction (native/OCR)
             -> document classification -> insurance classification
             -> segmentation -> field extraction -> validation
             -> candidates -> chunking -> embedding -> vector index

A document may yield one or more policy candidates. Never fabricates data:
fields that cannot be found are stored with ``evidence="not_found"`` so the UI
can display "Not found in uploaded document". Legacy ``PolicyExtraction`` rows
are still written for the first candidate so existing review flows keep
working.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import CandidateField, DocumentAnalysis, PolicyCandidate
from app.ai.factory import get_ai_provider
from app.ai.taxonomy import (
    DocumentClass,
    NON_INSURANCE_CLASSES,
    POLICY_BEARING_CLASSES,
    category_for_policy_type,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import (
    Document,
    DocumentAnalysis as DocumentAnalysisModel,
    DocumentChunk,
    PolicyCandidateField,
    PolicyCandidateRecord,
    PolicyExtraction,
)
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus
from app.utils.text_extract import TextExtractionError, extract_text

logger = logging.getLogger("koverly.processing")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_EXTRACTION_CHARS = 40000

NOT_INSURANCE_MESSAGE = (
    "This document does not appear to be an insurance policy or document. "
    "You can upload a policy copy, or add the policy manually."
)


def chunk_text(text: str) -> list[tuple[str, int | None]]:
    """Split text into overlapping chunks tracking page numbers.

    Pages are separated by form feeds produced during extraction.
    """
    chunks: list[tuple[str, int | None]] = []
    page_number = 1
    for page_text in text.split("\f"):
        cleaned = page_text.strip()
        if cleaned:
            start = 0
            while start < len(cleaned):
                end = start + CHUNK_SIZE
                piece = cleaned[start:end].strip()
                if piece:
                    chunks.append((piece, page_number))
                if end >= len(cleaned):
                    break
                start = end - CHUNK_OVERLAP
        page_number += 1
    return chunks


async def process_document(document_id: str) -> None:
    """Background entrypoint. Uses its own DB session."""
    async with SessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return
        document.status = DocumentStatus.PROCESSING.value
        document.processing_error = None
        await db.commit()

        try:
            await _run_pipeline(db, document)
            document.status = DocumentStatus.PROCESSED.value
            await db.commit()
            logger.info(
                "document_processed",
                extra={"extra_fields": {"document_id": document_id}},
            )
        except TextExtractionError as exc:
            document.status = DocumentStatus.FAILED.value
            document.processing_error = str(exc)
            await db.commit()
            logger.warning(
                "document_processing_failed",
                extra={"extra_fields": {"document_id": document_id, "reason": str(exc)}},
            )
        except Exception:  # noqa: BLE001
            await db.rollback()
            document = await db.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED.value
                document.processing_error = (
                    "Processing failed unexpectedly. You can retry or enter "
                    "details manually."
                )
                await db.commit()
            logger.exception("document_processing_error document_id=%s", document_id)


async def _run_pipeline(db: AsyncSession, document: Document) -> None:
    from app.integrations.storage import get_storage

    data = await get_storage().get(document.storage_key)
    result = extract_text(data, document.content_type)
    text = result.text
    document.page_count = result.page_count
    document.extracted_text = text[:200000]
    await db.flush()

    provider = get_ai_provider()
    sample = text[:MAX_EXTRACTION_CHARS]

    # 1) What is this document? (deterministic, cheap, always available)
    classifier = getattr(provider, "classify_document_class", None)
    if classifier is not None:
        document_class, class_confidence = classifier(text)
    else:
        hint = await provider.classify_document(sample)
        document_class = _hint_to_class(hint)
        class_confidence = 0.5

    is_insurance = document_class not in NON_INSURANCE_CLASSES
    if is_insurance and document.document_type == DocumentType.POLICY.value:
        pass  # keep the caller's hint
    elif document_class == DocumentClass.CLAIM_DOCUMENT.value:
        document.document_type = DocumentType.CLAIM.value

    # 2) Persist the analysis (replacing any previous one).
    analysis = await _upsert_analysis(
        db,
        document,
        document_class=document_class,
        class_confidence=class_confidence,
        source_kind=result.source_kind,
        is_insurance=is_insurance,
        ocr_used=result.ocr_used,
        provider=provider.name,
    )

    candidates: list[PolicyCandidate] = []
    if is_insurance and document_class in POLICY_BEARING_CLASSES:
        candidates = await provider.extract_candidates(
            sample, page_count=result.page_count
        )

    await _replace_candidates(db, document, analysis, candidates)

    # 3) Legacy extraction rows for the first candidate, so existing review
    #    and confirm flows continue to work unchanged.
    await _write_legacy_extractions(db, document, candidates)

    # 4) Chunking + embedding + vector index.
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )
    chunks = chunk_text(text)
    if chunks:
        contents = [c[0] for c in chunks]
        embeddings = await provider.embed(contents)
        for idx, ((content, page), embedding) in enumerate(zip(chunks, embeddings)):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    family_id=document.family_id,
                    policy_id=document.policy_id,
                    chunk_index=idx,
                    page_number=page,
                    content=content,
                    embedding=embedding,
                    embedding_model=provider.embedding_model,
                )
            )
    await db.flush()


def _hint_to_class(hint: str) -> str:
    if hint == "claim":
        return DocumentClass.CLAIM_DOCUMENT.value
    if hint == "policy":
        return DocumentClass.INSURANCE_POLICY.value
    return DocumentClass.OTHER_INSURANCE_DOCUMENT.value


async def _upsert_analysis(
    db: AsyncSession,
    document: Document,
    *,
    document_class: str,
    class_confidence: float,
    source_kind: str,
    is_insurance: bool,
    ocr_used: bool,
    provider: str,
) -> DocumentAnalysisModel:
    existing = (
        await db.execute(
            select(DocumentAnalysisModel).where(
                DocumentAnalysisModel.document_id == document.id
            )
        )
    ).scalar_one_or_none()

    message = None
    if not is_insurance:
        message = NOT_INSURANCE_MESSAGE

    analysis = existing or DocumentAnalysisModel(
        document_id=document.id, family_id=document.family_id
    )
    analysis.document_class = document_class
    analysis.document_class_confidence = class_confidence
    analysis.source_kind = source_kind
    analysis.is_insurance = is_insurance
    analysis.message = message
    analysis.provider = provider
    analysis.page_count = document.page_count
    analysis.ocr_used = ocr_used
    if existing is None:
        db.add(analysis)
    await db.flush()
    return analysis


async def _replace_candidates(
    db: AsyncSession,
    document: Document,
    analysis: DocumentAnalysisModel,
    candidates: list[PolicyCandidate],
) -> None:
    await db.execute(
        delete(PolicyCandidateRecord).where(
            PolicyCandidateRecord.document_id == document.id
        )
    )
    await db.flush()

    for index, candidate in enumerate(candidates):
        record = PolicyCandidateRecord(
            analysis_id=analysis.id,
            document_id=document.id,
            family_id=document.family_id,
            candidate_index=index,
            document_class=analysis.document_class,
            category=candidate.category,
            category_confidence=candidate.category_confidence,
            policy_type=candidate.policy_type,
            policy_type_confidence=candidate.policy_type_confidence,
            policy_subtype=candidate.policy_subtype,
            policy_subtype_confidence=candidate.policy_subtype_confidence,
            page_start=candidate.page_start,
            page_end=candidate.page_end,
            category_data=candidate.category_data or {},
            status=ExtractionStatus.PROPOSED.value,
        )
        db.add(record)
        await db.flush()
        for f in candidate.fields:
            db.add(
                PolicyCandidateField(
                    candidate_id=record.id,
                    field_name=f.field_name,
                    value=f.value,
                    confidence=f.confidence,
                    source_page=f.source_page,
                    source_text=f.source_text,
                    evidence=f.evidence,
                    review_status="ai_extracted",
                )
            )
    await db.flush()


async def _write_legacy_extractions(
    db: AsyncSession, document: Document, candidates: list[PolicyCandidate]
) -> None:
    await db.execute(
        delete(PolicyExtraction).where(PolicyExtraction.document_id == document.id)
    )
    if not candidates:
        await db.flush()
        return
    for f in candidates[0].fields:
        db.add(
            PolicyExtraction(
                document_id=document.id,
                family_id=document.family_id,
                policy_id=document.policy_id,
                field_name=f.field_name,
                value=f.value,
                confidence=f.confidence,
                source_page=f.source_page,
                found=f.evidence != "not_found" and f.value is not None,
                status=ExtractionStatus.PROPOSED.value,
            )
        )
    await db.flush()


async def reprocess_document(db: AsyncSession, document: Document) -> None:
    document.status = DocumentStatus.UPLOADED.value
    document.processing_error = None
    await db.commit()


async def list_extractions(
    db: AsyncSession, document_id: str
) -> list[PolicyExtraction]:
    rows = await db.execute(
        select(PolicyExtraction)
        .where(PolicyExtraction.document_id == document_id)
        .order_by(PolicyExtraction.field_name)
    )
    return list(rows.scalars().all())

