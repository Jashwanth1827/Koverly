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


@dataclass
class CandidateField:
    """A single extracted value with provenance and evidence state.

    ``evidence`` distinguishes what the document *says* from what was inferred:
    ``explicitly_found`` (stated in the text), ``inferred`` (derived from other
    explicit facts), ``uncertain`` (low confidence / partial OCR), or
    ``not_found``. ``value`` is None whenever the evidence is ``not_found``.
    """

    field_name: str
    value: str | None
    confidence: float = 0.0
    source_page: int | None = None
    source_text: str | None = None
    evidence: str = "not_found"

    def as_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "source_page": self.source_page,
            "source_text": self.source_text,
            "evidence": self.evidence,
        }


@dataclass
class PolicyCandidate:
    """One policy discovered in a document (a document may hold several)."""

    document_class: str = "insurance_policy"
    document_class_confidence: float = 0.0
    category: str = "other"
    category_confidence: float = 0.0
    policy_type: str = "other"
    policy_type_confidence: float = 0.0
    policy_subtype: str | None = None
    policy_subtype_confidence: float = 0.0
    page_start: int | None = None
    page_end: int | None = None
    fields: list[CandidateField] = field(default_factory=list)
    # Dynamic, category-specific extras that did not fit a universal field.
    category_data: dict[str, str] = field(default_factory=dict)

    def field_map(self) -> dict[str, CandidateField]:
        return {f.field_name: f for f in self.fields}


@dataclass
class DocumentAnalysis:
    """The full result of analysing one uploaded document."""

    document_class: str
    document_class_confidence: float
    is_insurance: bool
    message: str
    candidates: list[PolicyCandidate] = field(default_factory=list)
    summary: str = ""
    provider: str = "null"
    page_count: int | None = None


# Universal core fields every policy candidate may carry. Category-specific
# fields are added dynamically and are never mandatory.
UNIVERSAL_FIELDS = (
    "insurer",
    "policy_number",
    "policyholder_name",
    "sum_insured",
    "premium",
    "premium_frequency",
    "start_date",
    "expiry_date",
    "renewal_date",
    "maturity_date",
    "nominee",
    "status",
)


class AIProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def classify_document(self, text: str) -> str:
        """Return a document type hint (policy/claim/other)."""

    @abstractmethod
    async def extract_policy(self, text: str) -> list[ExtractedField]:
        """Extract structured policy fields with provenance."""

    async def classify_insurance(self, text: str) -> tuple[str, float]:
        """Return the insurance category and a confidence for the text.

        Default: derive from the coarse document hint. Providers that can do
        better (an LLM, or the deterministic local provider) override this.
        """
        hint = await self.classify_document(text)
        from app.ai.taxonomy import category_for_policy_type

        return category_for_policy_type(hint), 0.5 if hint != "other" else 0.0

    async def extract_candidates(
        self, text: str, *, page_count: int | None = None
    ) -> list[PolicyCandidate]:
        """Extract one or more policy candidates from a document.

        The default wraps ``extract_policy`` so a single-policy result is
        always produced, even for providers that have not implemented
        multi-policy segmentation.
        """
        fields = await self.extract_policy(text)
        category, category_conf = await self.classify_insurance(text)
        return [
            PolicyCandidate(
                category=category,
                category_confidence=category_conf,
                fields=[
                    CandidateField(
                        field_name=f.field_name,
                        value=f.value,
                        confidence=f.confidence,
                        source_page=f.source_page,
                        evidence="explicitly_found" if f.found else "not_found",
                    )
                    for f in fields
                ],
            )
        ]

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
