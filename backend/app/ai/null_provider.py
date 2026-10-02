"""Deterministic, dependency-free AI provider.

This provider performs *extractive* work only:

* field extraction via conservative regex patterns anchored on document labels,
* answering by selecting the most relevant sentences from retrieved content,
* hashing-based embeddings for local retrieval.

It never invents values. Anything it cannot find in the text is reported with
``found=False`` so the UI shows "Not found in uploaded document". This is the
default provider and keeps Koverly fully functional without any external API.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from app.ai.base import (
    AIProvider,
    AnswerResult,
    ExtractedField,
    NOT_FOUND_MESSAGE,
    SourceRef,
)
from app.utils.text import tokenize

EMBEDDING_DIM = 256

# Conservative field patterns. Each maps a canonical field name to one or more
# label-anchored regexes. We require a label so we do not grab arbitrary
# numbers as "premium".
_FIELD_PATTERNS: dict[str, list[str]] = {
    "policy_number": [
        r"(?:policy\s*(?:no|number|#)\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\-\/]{4,30})",
        r"(?:policy\s*id\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\-\/]{4,30})",
    ],
    "insurer": [
        r"(?:insurer|insurance\s+company|underwritten\s+by)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80})",
    ],
    "policyholder_name": [
        r"(?:policy\s*holder|name\s+of\s+(?:the\s+)?insured|insured\s+name|proposer)\s*[:\-]\s*([A-Za-z .'\-]{3,80})",
    ],
    "sum_insured": [
        r"(?:sum\s*insured|sum\s*assured|coverage\s*amount|insured\s*amount)\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?\s*(?:lakh|lac|crore|cr|k|m|million)?)",
    ],
    "premium": [
        r"(?:premium\s*(?:amount|paid|payable)?)\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)",
    ],
    "premium_frequency": [
        r"(?:premium\s*(?:frequency|mode)|payment\s*frequency|mode\s*of\s*payment)\s*[:\-]\s*([A-Za-z ]{4,20})",
    ],
    "start_date": [
        r"(?:start\s*date|commencement\s*date|inception\s*date|effective\s*from|policy\s*period\s*from)\s*[:\-]?\s*([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
    ],
    "expiry_date": [
        r"(?:expiry\s*date|expiration\s*date|end\s*date|valid\s*(?:up\s*)?to|policy\s*period\s*(?:to|upto|up\s*to))\s*[:\-]?\s*([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
    ],
    "renewal_date": [
        r"(?:renewal\s*date|due\s*date|next\s*renewal)\s*[:\-]?\s*([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
    ],
    "nominee": [
        r"(?:nominee(?:\s*name)?)\s*[:\-]\s*([A-Za-z .'\-]{3,80})",
    ],
    "tpa": [
        r"(?:tpa|third\s*party\s*administrator)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80})",
    ],
    "claim_contact": [
        r"(?:claim\s*(?:contact|helpline|phone|number)|toll\s*free)\s*[:\-]?\s*([0-9][0-9\-\s]{6,20})",
    ],
    "maturity_date": [
        r"(?:maturity\s*date)\s*[:\-]?\s*([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
    ],
    "waiting_period": [
        r"(?:waiting\s*period)\s*[:\-]?\s*([0-9]+\s*(?:days?|months?|years?))",
    ],
    "deductible": [
        r"(?:deductible|excess)\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)",
    ],
}

_TYPE_HINTS: dict[str, list[str]] = {
    "health": ["health insurance", "mediclaim", "hospitalisation", "hospitalization", "tpa"],
    "life": ["life insurance", "term plan", "sum assured", "maturity", "nominee"],
    "motor": ["motor insurance", "vehicle", "car insurance", "bike", "registration number"],
    "home": ["home insurance", "household", "property insurance", "fire insurance"],
    "travel": ["travel insurance", "trip", "baggage", "flight delay"],
    "personal_accident": ["personal accident", "accidental death", "disability"],
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    return [p for p in parts if len(p) > 15]


def _tokenize(text: str) -> list[str]:
    return tokenize(text)


class NullProvider(AIProvider):
    name = "null"

    @property
    def embedding_model(self) -> str:
        return f"local-hash-{EMBEDDING_DIM}"

    async def classify_document(self, text: str) -> str:
        lowered = text.lower()
        scores = {
            ptype: sum(lowered.count(hint) for hint in hints)
            for ptype, hints in _TYPE_HINTS.items()
        }
        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            return "other"
        return best

    async def extract_policy(self, text: str) -> list[ExtractedField]:
        fields: list[ExtractedField] = []
        for name, patterns in _FIELD_PATTERNS.items():
            match, page = _search_with_page(text, patterns)
            if match:
                value = _normalize(match.strip())
                fields.append(
                    ExtractedField(
                        field_name=name,
                        value=value,
                        confidence=0.7,
                        source_page=page,
                        found=True,
                    )
                )
            else:
                fields.append(
                    ExtractedField(
                        field_name=name,
                        value=None,
                        confidence=0.0,
                        source_page=None,
                        found=False,
                    )
                )
        return fields

    async def answer_question(
        self, question: str, contexts: list[SourceRef]
    ) -> AnswerResult:
        if not contexts:
            return AnswerResult(
                answer=NOT_FOUND_MESSAGE,
                sources=[],
                grounded=False,
                provider=self.name,
            )
        q_tokens = set(_tokenize(question))
        scored: list[tuple[float, SourceRef]] = []
        for ctx in contexts:
            overlap = len(q_tokens & set(_tokenize(ctx.snippet)))
            if overlap:
                scored.append((overlap / (len(q_tokens) or 1), ctx))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:3]
        if not top:
            return AnswerResult(
                answer=NOT_FOUND_MESSAGE,
                sources=[],
                grounded=False,
                provider=self.name,
            )
        # Extractive answer: quote the most relevant retrieved passages.
        lines = []
        for _, ctx in top:
            lines.append(f"Policy says: “{ctx.snippet.strip()}”")
        answer = "\n\n".join(lines)
        sources = [ctx for _, ctx in top]
        return AnswerResult(
            answer=answer,
            sources=sources,
            grounded=True,
            provider=self.name,
        )

    async def summarize_document(self, text: str) -> str:
        sentences = _split_sentences(text)
        if not sentences:
            return ""
        counts = Counter(_tokenize(text))
        def score(s: str) -> float:
            toks = _tokenize(s)
            if not toks:
                return 0.0
            return sum(counts[t] for t in toks) / len(toks)
        ranked = sorted(sentences, key=score, reverse=True)[:4]
        # Preserve original order for readability.
        ordered = [s for s in sentences if s in set(ranked)]
        return " ".join(ordered)[:1200]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(t) for t in texts]


def _search_with_page(
    text: str, patterns: list[str]
) -> tuple[str | None, int | None]:
    """Search patterns across the whole text, tracking a page approximation.

    Page numbers are approximated by counting form-feed characters used as
    page separators during text extraction.
    """
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            page = text[: match.start(1)].count("\f") + 1
            return match.group(1), page
    return None, None


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashing embedding (bag-of-words hashed into fixed dims).

    Not semantically rich, but stable, offline, and adequate for keyword-level
    retrieval. Swap the provider's ``embed`` for a real model in production.
    """
    vec = [0.0] * EMBEDDING_DIM
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % EMBEDDING_DIM
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec
