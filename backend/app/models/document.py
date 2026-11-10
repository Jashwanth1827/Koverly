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
    analysis = relationship(
        "DocumentAnalysis",
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )
    candidates = relationship(
        "PolicyCandidateRecord",
        back_populates="document",
        cascade="all, delete-orphan",
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


class DocumentAnalysis(Base, UUIDMixin, TimestampMixin):
    """The result of automatically understanding an uploaded document.

    Records what the document *is* (document class) and how it was read, so the
    UI can tell the user what was found without asking them to classify
    anything. One document has at most one current analysis; reprocessing
    replaces it.
    """

    __tablename__ = "document_analyses"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )

    document_class: Mapped[str] = mapped_column(String(32), nullable=False)
    document_class_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # text_document | scanned_document | image_document
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    is_insurance: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # A human-readable explanation when nothing could be turned into a policy
    # (non-insurance document, unreadable scan, ...). Never a fabricated policy.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    document = relationship("Document", back_populates="analysis")
    candidates = relationship(
        "PolicyCandidateRecord",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )


class PolicyCandidateRecord(Base, UUIDMixin, TimestampMixin):
    """A policy discovered in a document, pending user review.

    A document may yield several candidates (e.g. a bundle holding health,
    motor and life policies). Each carries its own classification and page
    range. Nothing here is authoritative until the user confirms it.
    """

    __tablename__ = "policy_candidates"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("document_analyses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[str] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Set once the candidate is confirmed into a stored policy.
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("policies.id", ondelete="SET NULL"), index=True, nullable=True
    )

    candidate_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_class: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    category_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    policy_type: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    policy_type_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    policy_subtype: Mapped[str | None] = mapped_column(String(40), nullable=True)
    policy_subtype_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)

    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Dynamic, category-specific extras that did not map to a universal field.
    category_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # proposed | confirmed | rejected
    status: Mapped[str] = mapped_column(
        String(16), default=ExtractionStatus.PROPOSED.value, index=True, nullable=False
    )

    analysis = relationship("DocumentAnalysis", back_populates="candidates")
    document = relationship("Document", back_populates="candidates")
    fields = relationship(
        "PolicyCandidateField",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )


class PolicyCandidateField(Base, UUIDMixin, TimestampMixin):
    """A single value on a policy candidate, with provenance.

    ``evidence`` records whether the value was explicitly present in the
    document, inferred from other facts, uncertain, or not found at all.
    ``review_status`` records whether the user has confirmed or edited it.
    """

    __tablename__ = "policy_candidate_fields"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("policy_candidates.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # explicitly_found | inferred | uncertain | not_found
    evidence: Mapped[str] = mapped_column(String(20), default="not_found", nullable=False)
    # ai_extracted | user_confirmed | user_edited
    review_status: Mapped[str] = mapped_column(
        String(20), default="ai_extracted", nullable=False
    )

    candidate = relationship("PolicyCandidateRecord", back_populates="fields")


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
