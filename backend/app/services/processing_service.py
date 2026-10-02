"""Document processing pipeline.

Runs asynchronously after upload::

    document -> text extraction -> classification -> field extraction
             -> validation -> chunking -> embedding -> vector index

Never fabricates data: fields that cannot be found are stored with
``found=False`` so the UI can display "Not found in uploaded document".
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_ai_provider
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Document, DocumentChunk, PolicyExtraction
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus
from app.utils.text_extract import TextExtractionError, extract_text

logger = logging.getLogger("koverly.processing")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_EXTRACTION_CHARS = 40000


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
    text, page_count = extract_text(data, document.content_type)
    document.page_count = page_count
    document.extracted_text = text[:200000]
    await db.flush()

    provider = get_ai_provider()

    # Classification may refine the document type.
    if document.document_type == DocumentType.POLICY.value:
        predicted = await provider.classify_document(text[:MAX_EXTRACTION_CHARS])
        if predicted == "claim":
            document.document_type = DocumentType.CLAIM.value

    # Field extraction (only for policy documents).
    if document.document_type == DocumentType.POLICY.value:
        fields = await provider.extract_policy(text[:MAX_EXTRACTION_CHARS])
        # Replace any prior proposals for this document (idempotent re-runs).
        await db.execute(
            delete(PolicyExtraction).where(
                PolicyExtraction.document_id == document.id
            )
        )
        for f in fields:
            db.add(
                PolicyExtraction(
                    document_id=document.id,
                    family_id=document.family_id,
                    policy_id=document.policy_id,
                    field_name=f.field_name,
                    value=f.value,
                    confidence=f.confidence,
                    source_page=f.source_page,
                    found=f.found,
                    status=ExtractionStatus.PROPOSED.value,
                )
            )
        await db.flush()

    # Chunking + embedding + vector index.
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
