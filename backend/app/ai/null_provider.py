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

# A date, in the formats insurers commonly print (numeric or "12 Apr 2024").
# Uses horizontal whitespace so a match never spans two lines.
_DATE = (
    r"([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}"
    r"|[0-9]{1,2}[ \t\-][A-Za-z]{3,9}[ \t,\-]+[0-9]{4})"
)
# A money amount, tolerating currency symbols, thousands separators and words
# like "lakh"/"crore". Horizontal whitespace only, so it never jumps lines.
_MONEY = (
    r"([0-9][0-9,]*(?:\.\d+)?(?:[ \t]*(?:lakh|lakhs|lac|lacs|crore|crores|cr|k|m|million))?)"
)
# A label may be separated from its value by a colon/dash or just whitespace.
_CUR = r"(?:rs\.?|inr|\u20b9|\$)?[ \t]*"

# Conservative field patterns. Each maps a canonical field name to one or more
# label-anchored regexes. We require a label so we do not grab arbitrary
# numbers as "premium". Patterns are ordered most-specific first.
_FIELD_PATTERNS: dict[str, list[str]] = {
    "policy_number": [
        # "Policy No.:", "Policy No:", "Policy Number -", "Policy #"
        rf"(?:policy\s*(?:no|number|#)\.?\s*[:\-#]?\s*)([A-Za-z0-9][A-Za-z0-9\-\/]{{3,40}})",
        rf"(?:policy\s*id\s*[:\-]?\s*)([A-Za-z0-9][A-Za-z0-9\-\/]{{3,40}})",
    ],
    "insurer": [
        r"(?:insurer|insurance\s+company|underwritten\s+by|issued\s+by)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80})",
        # Company-style heading, e.g. "HDFC ERGO General Insurance Company
        # Limited". Excludes title lines that merely contain the word "policy".
        r"^(?!.*\bpolicy\b)([A-Z][A-Za-z0-9&.,'\- ]{2,80}?(?:Insurance|Assurance)\s+(?:Company|Co\.?|Limited|Ltd\.?)[A-Za-z0-9&.,'\- ]{0,30})$",
        r"^(?!.*\bpolicy\b)([A-Z][A-Za-z0-9&.,'\- ]{2,80}?(?:Insurance|Assurance|Life)\b[^\n]{0,40})$",
        # Abbreviation-style insurer names, e.g. "LIC of India".
        r"^([A-Z]{2,8}\s+of\s+[A-Z][A-Za-z]+(?:[ \t][A-Z][A-Za-z]+){0,3})$",
    ],
    "policyholder_name": [
        r"(?:policy\s*holder(?:\s*name)?|name\s+of\s+(?:the\s+)?(?:insured|policyholder)|insured\s*name|proposer(?:\s*name)?)\s*[:\-]\s*([A-Za-z .'\-]{3,80})",
    ],
    "sum_insured": [
        rf"(?:sum\s*insured|sum\s*assured|coverage\s*amount|insured\s*amount|idv|insured\s*declared\s*value)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
    "premium": [
        rf"(?:premium\s*(?:amount|paid|payable)?|total\s*premium)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
    "premium_frequency": [
        r"(?:premium\s*(?:frequency|mode)|payment\s*(?:frequency|mode)|mode\s*of\s*payment)\s*[:\-]\s*([A-Za-z ]{4,20})",
    ],
    "start_date": [
        rf"(?:start\s*date|commencement\s*date|date\s*of\s*commencement|inception\s*date|effective\s*(?:from|date)|policy\s*period\s*(?:from|start)|period\s*of\s*insurance|insurance\s*period|risk\s*(?:start|commencement)\s*date)\s*[:\-]?\s*{_DATE}",
        # "Policy Period: 01/04/2024 to 31/03/2025" - first date is the start.
        rf"(?:policy\s*period|period\s*of\s*insurance|insurance\s*period)\s*[:\-]?\s*{_DATE}\s*(?:to|upto|up\s*to|-|\u2013)",
    ],
    "expiry_date": [
        rf"(?:expiry\s*date|expiration\s*date|end\s*date|date\s*of\s*expiry|valid\s*(?:up\s*)?to|policy\s*period\s*(?:to|upto|up\s*to)|risk\s*end\s*date)\s*[:\-]?\s*{_DATE}",
        # "Policy Period: 01/04/2024 to 31/03/2025" - the date after "to".
        rf"(?:policy\s*period|period\s*of\s*insurance|insurance\s*period)\s*[:\-]?\s*[0-9]{{1,4}}[\-/][0-9]{{1,2}}[\-/][0-9]{{1,4}}\s*(?:to|upto|up\s*to|-|\u2013)\s*{_DATE}",
    ],
    "renewal_date": [
        rf"(?:renewal\s*date|due\s*date|next\s*renewal|renewal\s*due)\s*[:\-]?\s*{_DATE}",
    ],
    "nominee": [
        r"(?:nominee(?:\s*name)?)\s*[:\-]\s*([A-Za-z .'\-]{3,80})",
    ],
    "tpa": [
        r"(?:tpa|third\s*party\s*administrator)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80})",
    ],
    "claim_contact": [
        r"(?:claim\s*(?:contact|helpline|phone|number)|toll\s*free|helpline)\s*[:\-]?\s*([0-9][0-9\-\s]{6,20})",
    ],
    "maturity_date": [
        rf"(?:maturity\s*date|date\s*of\s*maturity)\s*[:\-]?\s*{_DATE}",
    ],
    "waiting_period": [
        r"(?:waiting\s*period|pre[-\s]?existing\s*waiting\s*period)\s*[:\-]?\s*([0-9]+\s*(?:days?|months?|years?))",
    ],
    "deductible": [
        rf"(?:deductible|excess)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
}

_TYPE_HINTS: dict[str, list[str]] = {
    "health": ["health insurance", "mediclaim", "hospitalisation", "hospitalization", "tpa"],
    "life": ["life insurance", "term plan", "sum assured", "maturity", "endowment", "jeevan"],
    "motor": ["motor insurance", "vehicle", "car insurance", "private car", "package policy", "registration number", "idv", "two wheeler", "bike"],
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
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
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
