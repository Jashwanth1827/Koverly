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
    NOT_FOUND_MESSAGE,
    AIProvider,
    AnswerResult,
    ExtractedField,
    SourceRef,
)
from app.utils.text import tokenize

EMBEDDING_DIM = 256

# Conservative field patterns. Each maps a canonical field name to one or more
# label-anchored regexes. We require a label so we do not grab arbitrary
# numbers as "premium".
_DATE = (
    r"(?:[0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}"
    r"|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})"
)

# Labels are anchored to the start of a line so wording such as
# "Welcome to ... Insurance Company Limited" is not mistaken for a label.
# Patterns tolerate the value being on the next line, which is common in
# table-based policy schedules extracted from PDFs.
_FIELD_PATTERNS: dict[str, list[str]] = {
    "policy_number": [
        r"(?im)^[ \t]*(?:policy\s*(?:no|number|#)\.?|policy\s*id)\s*[:\-.]?\s*"
        r"([A-Z0-9][A-Z0-9\-/ ]{3,39}[A-Z0-9])[ \t]*$",
        r"(?i)(?:policy\s*(?:no|number|#)\.?)\s*[:\-.]?[ \t]*"
        r"([A-Z0-9][A-Z0-9\-/ ]{3,39}[A-Z0-9])",
    ],
    "insurer": [
        r"(?im)^[ \t]*(?:insurer|underwritten\s+by)\s*[:\-.]?\s*"
        r"([A-Za-z0-9 .,&'\-]{3,80})[ \t]*$",
        r"(?im)^[ \t]*insurance\s+company\s*[:\-.]?\s*"
        r"([A-Za-z0-9 .,&'\-]{3,80})[ \t]*$",
    ],
    "policyholder_name": [
        r"(?im)^[ \t]*(?:policy\s*holder(?:['\u2019]?s)?(?:\s*name)?|name\s+of\s+(?:the\s+)?insured"
        r"|insured\s+name|proposer)(?!\s*(?:state|address|gender))\s*[:\-.]?\s*"
        r"([A-Za-z .'\-]{3,80})[ \t]*$",
    ],
    "sum_insured": [
        r"(?im)^[ \t]*total\s+sum\s+insured(?:\s*\([^)]*\))?\s*[:\-.]?\s*"
        r"(?:rs\.?|inr|₹|\$)?\s*"
        r"([0-9][0-9,]*(?:\.\d+)?\s*(?:lakh|lac|crore|cr|k|m|million)?)[ \t]*$",
        r"(?im)^[ \t]*(?:base\s+)?sum\s+(?:insured|assured)(?:\s*\([^)]*\))?\s*[:\-.]?\s*"
        r"(?:rs\.?|inr|₹|\$)?\s*"
        r"([0-9][0-9,]*(?:\.\d+)?\s*(?:lakh|lac|crore|cr|k|m|million)?)[ \t]*$",
        r"(?i)(?:sum\s*insured|sum\s*assured|coverage\s*amount|insured\s*amount)\s*[:\-]?[ \t]*"
        r"(?:rs\.?|inr|₹|\$)?[ \t]*"
        r"([0-9][0-9,]*(?:\.\d+)?\s*(?:lakh|lac|crore|cr|k|m|million)?)",
    ],
    "premium": [
        r"(?im)^[ \t]*gross\s+premium(?:\s*\([^)]*\))?\s*[:\-.]?\s*"
        r"(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)[ \t]*$",
        r"(?im)^[ \t]*premium\s*(?:amount|paid|payable)?\s*[:\-.]?\s*"
        r"(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)[ \t]*$",
    ],
    "premium_frequency": [
        r"(?im)^[ \t]*(?:premium\s*(?:frequency|mode)|payment\s*frequency|mode\s*of\s*payment)"
        r"\s*[:\-.]?\s*([A-Za-z ]{4,20})[ \t]*$",
    ],
    "start_date": [
        rf"(?i)(?:policy\s+)?period\s+(?:of\s+)?(?:from\s+)?({_DATE})",
        rf"(?im)^[ \t]*(?:start\s*date|commencement\s*date|date\s+of\s+commencement"
        rf"|risk\s*commencement\s*date|effective\s+from|policy\s*period\s*from)"
        rf"\s*[:\-]?\s*({_DATE})[ \t]*$",
    ],
    "expiry_date": [
        rf"(?i)(?:policy\s+)?period\s+(?:of\s+)?{_DATE}\s+(?:to|till|upto|up\s+to)\s+({_DATE})",
        rf"(?im)^[ \t]*(?:expiry\s*date|expiration\s*date|end\s*date|valid\s*(?:up\s*)?to"
        rf"|policy\s*period\s*(?:to|upto|up\s*to))\s*[:\-]?\s*({_DATE})[ \t]*$",
    ],
    "renewal_date": [
        rf"(?im)^[ \t]*(?:renewal\s*date|due\s*date|next\s*renewal)\s*[:\-]?\s*"
        rf"({_DATE})[ \t]*$",
    ],
    "nominee": [
        r"(?im)^[ \t]*nominee(?:\s*name)?(?!\s*details\b)\s*[:\-.]?\s*"
        r"([A-Za-z .'\-]{3,80})[ \t]*$",
    ],
    "tpa": [
        r"(?im)^[ \t]*(?:tpa|third\s*party\s*administrator|claim\s*administrator)"
        r"\s*[:\-.]?\s*([A-Za-z0-9 .,&'\-]{3,80})[ \t]*$",
    ],
    "claim_contact": [
        r"(?im)^[ \t]*(?:claim\s*(?:contact|helpline|phone|number)|toll\s*free)"
        r"\s*[:\-.]?\s*([0-9][0-9\-\s]{6,20})[ \t]*$",
    ],
    "maturity_date": [
        rf"(?im)^[ \t]*(?:maturity\s*date|date\s+of\s+maturity)\s*[:\-]?\s*"
        rf"({_DATE})[ \t]*$",
    ],
    "waiting_period": [
        r"(?im)^[ \t]*waiting\s*period\s*[:\-.]?\s*"
        r"([0-9]+\s*(?:days?|months?|years?))[ \t]*$",
    ],
    "deductible": [
        r"(?im)^[ \t]*(?:deductible|excess)\s*[:\-.]?\s*"
        r"(?:rs\.?|inr|₹|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)[ \t]*$",
    ],
}

_COMPANY_NAME = re.compile(
    r"([A-Z][A-Za-z0-9&.'-]*(?:[ \t]+[A-Z][A-Za-z0-9&.'-]*){0,4}[ \t]+"
    r"(?:General[ \t]+)?(?:Insurance|Assurance)[ \t]+(?:Company|Co\.?|Corporation)"
    r"(?:[ \t]+(?:Limited|Ltd\.?))?)"
)
# Insurers written as "<X> Insurance Corporation of <Country>", e.g. the
# Life Insurance Corporation of India, and the bare LIC full name.
_COMPANY_CORPORATION = re.compile(
    r"([A-Z][A-Za-z0-9&.'-]*(?:[ \t]+[A-Z][A-Za-z0-9&.'-]*){0,3}[ \t]+"
    r"(?:Insurance|Assurance|INSURANCE|ASSURANCE)[ \t]+"
    r"(?:Corporation|CORPORATION)[ \t]+(?:of|OF)[ \t]+[A-Za-z]+)"
)

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


# Markdown/table decorations that would otherwise sit between a label and its
# value. Front-ends (docs, wikis) commonly emit ``**Insurer:** Acme`` or
# spreadsheet-style ``Insurer | Acme`` rows.
_MD_EMPHASIS = re.compile(r"[*_`~]{1,3}")
_LIST_BULLET = re.compile(r"(?m)^[ \t]*[-+>]\s+")
# Qualifiers insurers add after a label, e.g. ``Premium (in INR)`` or
# ``Sum Insured (Rs.)``. They sit between the label and the separator.
_LABEL_QUALIFIER = re.compile(r"[ \t]*\([^)]{0,40}\)")


def _clean_layout(text: str) -> str:
    """Strip markup so label/value pairs match regardless of source format.

    Handles Markdown emphasis and headings, table pipes and commas used as
    cell separators, list bullets, and parenthetical label qualifiers such as
    ``Premium (in INR):``. Line structure is preserved because the field
    patterns are line-anchored.
    """
    cleaned_lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = _MD_EMPHASIS.sub("", raw).strip()
        line = re.sub(r"^#+\s*", "", line)
        if _LIST_BULLET.match(line):
            line = _LIST_BULLET.sub("", line)
        # A table or CSV row joins cells with ``|`` or ``,``; turn the first
        # separator into a ``:`` so the standard ``Label: value`` rule applies.
        if "|" in line and ":" not in line.split("|", 1)[0]:
            line = line.replace("|", ":", 1)
        elif "," in line and ":" not in line.split(",", 1)[0]:
            head = line.split(",", 1)[0]
            if re.fullmatch(r"[A-Za-z][A-Za-z /#.'-]*", head.strip()):
                line = line.replace(",", ":", 1)
        # Drop a qualifier that sits between the label and its separator.
        head, sep, tail = line.partition(":")
        if sep:
            head = _LABEL_QUALIFIER.sub("", head).strip()
            line = f"{head}{sep}{tail}"
        elif not any(ch.isdigit() for ch in line):
            line = _LABEL_QUALIFIER.sub("", line).strip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


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
        # Normalise markup (Markdown, tables, CSV) once so every pattern sees a
        # consistent ``Label: value`` layout.
        text = _clean_layout(text)
        fields: list[ExtractedField] = []
        for name, patterns in _FIELD_PATTERNS.items():
            match, page = _search_with_page(text, patterns)
            if not match and name == "insurer":
                company = _COMPANY_NAME.search(text) or _COMPANY_CORPORATION.search(
                    text
                )
                if company:
                    match = company.group(1)
                    page = text[: company.start(1)].count("\f") + 1
            if match:
                value = _normalize(match.strip())
                if name == "policy_number":
                    value = re.sub(r"\s+", "", value)
                elif name in {"insurer", "policyholder_name", "nominee", "tpa"}:
                    value = value.rstrip(" .,")
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
