"""Document, extraction, and assistant schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    policy_id: str | None
    claim_id: str | None
    original_filename: str
    content_type: str
    size_bytes: int
    document_type: str
    status: str
    processing_error: str | None
    page_count: int | None
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(BaseModel):
    policy_id: str | None = None
    document_type: str | None = None


class SignedUrlOut(BaseModel):
    url: str
    expires_in: int


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    policy_id: str | None
    field_name: str
    value: str | None
    confidence: float
    source_page: int | None
    found: bool
    status: str
    created_at: datetime


class ExtractionConfirm(BaseModel):
    """User review of AI-proposed fields.

    Confirmed values are applied to the linked policy. Rejected fields are
    ignored. Fields not listed keep their proposed state.
    """

    policy_id: str | None = None
    confirm: dict[str, str] = Field(default_factory=dict)
    reject: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    family_id: str
    policy_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SourceOut(BaseModel):
    document_id: str
    document_name: str
    page_number: int | None
    snippet: str
    label: str


class RecordMatchOut(BaseModel):
    """A stored record surfaced by the assistant's search tool."""

    kind: str
    id: str
    title: str
    subtitle: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    grounded: bool
    provider: str
    disclaimer: str
    matches: list[RecordMatchOut] = Field(default_factory=list)
