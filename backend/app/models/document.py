"""Document vault, extraction, and RAG chunk models."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus


class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "documents"

    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("policies.id", ondelete="SET NULL"), index=True, nullable=True
    )
    claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), index=True, nullable=True
    )
    uploaded_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Opaque storage key — never a public URL.
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    document_type: Mapped[str] = mapped_column(
        String(16), default=DocumentType.POLICY.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=DocumentStatus.UPLOADED.value, index=True, nullable=False
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    policy = relationship("Policy", back_populates="documents")
    claim = relationship("Claim", back_populates="documents")
    extractions = relationship(
        "PolicyExtraction", back_populates="document", cascade="all, delete-orphan"
    )
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class PolicyExtraction(Base, UUIDMixin, TimestampMixin):
    """A single AI-proposed field extracted from a document.

    Extractions are proposals until a user confirms them; confirmed values are
    what the application treats as authoritative.
    """

    __tablename__ = "policy_extractions"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("policies.id", ondelete="SET NULL"), index=True, nullable=True
    )

    field_name: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    found: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ExtractionStatus.PROPOSED.value, index=True, nullable=False
    )

    document = relationship("Document", back_populates="extractions")


class DocumentChunk(Base, UUIDMixin, TimestampMixin):
    """A chunk of document text plus its embedding for retrieval.

    Embeddings are stored as JSON float arrays for portability. A production
    Postgres deployment can add a pgvector column and an ivfflat/hnsw index
    without changing the retrieval interface.
    """

    __tablename__ = "document_chunks"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("policies.id", ondelete="SET NULL"), index=True, nullable=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)

    document = relationship("Document", back_populates="chunks")
