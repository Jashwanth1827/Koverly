"""AI provider abstraction.

The application depends on this interface, not on any specific vendor. New
providers (OpenAI, Anthropic, local models, ...) implement ``AIProvider`` and
are selected via configuration.

A deterministic ``NullProvider`` is always available so the product works
offline and never fabricates policy facts: it performs pattern-based
extraction and extractive (grounded) answering only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractedField:
    """A single extracted field with provenance.

    ``found`` is False when the information is genuinely absent from the
    document — callers must render these as "Not found in uploaded document".
    """

    field_name: str
    value: str | None
    confidence: float
    source_page: int | None = None
    found: bool = True

    def as_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "source_page": self.source_page,
            "found": self.found,
        }


@dataclass
class SourceRef:
    document_id: str
    document_name: str
    page_number: int | None
    snippet: str

    def label(self) -> str:
        page = f" — Page {self.page_number}" if self.page_number else ""
        return f"Source: {self.document_name}{page}"


@dataclass
class RecordMatch:
    """A stored record surfaced by the assistant's search tool.

    ``kind`` is one of policy / family_member / claim / document. Only a title
    and subtitle are exposed; document contents are never included.
    """

    kind: str
    id: str
    title: str
    subtitle: str | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
        }


@dataclass
class AnswerResult:
    """A grounded answer.

    ``grounded`` is False when no supporting content was retrieved; in that
    case the UI must present the canonical "couldn't find" message and must
    not treat the text as policy fact.
    """

    answer: str
    sources: list[SourceRef] = field(default_factory=list)
    grounded: bool = False
    provider: str = "null"
    disclaimer: str = ""
    matches: list[RecordMatch] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": [
                {
                    "document_id": s.document_id,
                    "document_name": s.document_name,
                    "page_number": s.page_number,
                    "snippet": s.snippet,
                    "label": s.label(),
                }
                for s in self.sources
            ],
            "grounded": self.grounded,
            "provider": self.provider,
            "disclaimer": self.disclaimer,
            "matches": [m.as_dict() for m in self.matches],
        }


NOT_FOUND_MESSAGE = "I couldn't find that information in your uploaded policy documents."


class AIProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def classify_document(self, text: str) -> str:
        """Return a document type hint (policy/claim/other)."""

    @abstractmethod
    async def extract_policy(self, text: str) -> list[ExtractedField]:
        """Extract structured policy fields with provenance."""

    @abstractmethod
    async def answer_question(
        self, question: str, contexts: list[SourceRef]
    ) -> AnswerResult:
        """Answer strictly from the provided retrieved contexts."""

    @abstractmethod
    async def summarize_document(self, text: str) -> str:
        """Return a short neutral summary of a document."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for the given texts."""

    @property
    def embedding_model(self) -> str:
        return "unknown"

    async def analyze_coverage(self, context_summary: str) -> list[str]:
        """Optional coverage observations. Default: none."""
        return []
