"""Deterministic, dependency-free AI provider.

This provider performs *extractive* work only:

* document classification (what the file is) and insurance classification
  (category / type / subtype) from the document's own vocabulary,
* multi-policy segmentation for bundles holding several policies,
* field extraction via conservative regex patterns anchored on document
  labels, with source page and source text for every value,
* answering by selecting the most relevant sentences from retrieved content,
* hashing-based embeddings for local retrieval.

It never invents values. Anything it cannot find in the text is reported with
``found=False`` / ``evidence="not_found"`` so the UI shows "Not found in
uploaded document". This is the default provider and keeps Koverly fully
functional without any external API.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from app.ai.base import (
    AIProvider,
    AnswerResult,
    CandidateField,
    ExtractedField,
    NOT_FOUND_MESSAGE,
    PolicyCandidate,
    SourceRef,
    UNIVERSAL_FIELDS,
)
from app.ai.taxonomy import (
    CATEGORY_TO_POLICY_TYPE,
    DocumentClass,
    InsuranceCategory,
    POLICY_BEARING_CLASSES,
    POLICY_TYPES_BY_CATEGORY,
    category_for_policy_type,
    fields_for_category,
    valid_policy_type,
)
from app.utils.text import tokenize

EMBEDDING_DIM = 256

# A date, in the formats insurers commonly print (numeric or "12 Apr 2024").
# Uses horizontal whitespace so a match never spans two lines.
_DATE = (
    r"([0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}"
    r"|[0-9]{1,2}[ \t\-][A-Za-z]{3,9}[ \t,\-]+[0-9]{4})"
)
# Same shape without a capture group, for the leading date of a range where the
# value we want is the *second* date.
_DATE_NC = (
    r"(?:[0-9]{1,4}[\-/][0-9]{1,2}[\-/][0-9]{1,4}"
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
        # Spaced numeric policy numbers, e.g. "Policy No : 2805 2035 3959 6703 000".
        rf"(?:policy\s*(?:no|number|#)\.?\s*[:\-#]?\s*)([0-9][0-9 \t\-]{{6,40}}[0-9])",
        rf"(?:policy\s*(?:no|number|#)\.?\s*[:\-#]?\s*)([A-Za-z0-9][A-Za-z0-9\-\/]{{3,40}})",
        rf"(?:policy\s*id\s*[:\-]?\s*)([A-Za-z0-9][A-Za-z0-9\-\/]{{3,40}})",
    ],
    "insurer": [
        r"(?:insurer|insurance\s+company|underwritten\s+by|issued\s+by)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80})",
        # Company-style heading, e.g. "HDFC ERGO General Insurance Company
        # Limited". Excludes title lines that merely contain the word "policy"
        # or boilerplate such as "For and on behalf of ...".
        r"^(?!.*\b(?:policy|for\s+and\s+on\s+behalf|on\s+behalf|authorised|authorized|signatory|welcome|please|dear)\b)([A-Z][A-Za-z0-9&.,'\- ]{2,80}?(?:Insurance|Assurance)\s+(?:Company|Co\.?|Limited|Ltd\.?)[A-Za-z0-9&.,'\- ]{0,30})$",
        r"^(?!.*\b(?:policy|for\s+and\s+on\s+behalf|on\s+behalf|authorised|authorized|signatory|welcome|please|dear)\b)([A-Z][A-Za-z0-9&.,'\- ]{2,80}?(?:Insurance|Assurance|Life)\b[^\n]{0,40})$",
        # Abbreviation-style insurer names, e.g. "LIC of India".
        r"^([A-Z]{2,8}\s+of\s+[A-Z][A-Za-z]+(?:[ \t][A-Z][A-Za-z]+){0,3})$",
    ],
    "policyholder_name": [
        # Line-anchored label so a mid-line relationship label such as
        # "Relationship to Policyholder: Wife" is never mistaken for the name.
        r"^\s*(?:policy\s*holder['\u2019]?s?\s*name|name\s+of\s+(?:the\s+)?(?:insured|policyholder)|insured\s*name|proposer(?:\s*name)?|policy\s*holder\s*[:\-])\s*[:\-]?\s*(.+)$",
        r"(?:dear|issued\s+to|in\s+the\s+name\s+of)\s+(?:mr|mrs|ms|shri|smt|dr)\.?\s+([A-Za-z][A-Za-z .'\-]{2,60})",
        r"^(?:mr|mrs|ms|shri|smt|dr)\.?\s+([A-Za-z][A-Za-z .'\-]{2,60})$",
    ],
    "sum_insured": [
        rf"(?:total\s*sum\s*insured)\s*[:\-]?\s*(?:@\)?\s*)?{_CUR}{_MONEY}",
        rf"(?:base\s*sum\s*insured)\s*[:\-]?\s*(?:@\)?\s*)?{_CUR}{_MONEY}",
        rf"(?:sum\s*insured|sum\s*assured|coverage\s*amount|insured\s*amount|idv|insured\s*declared\s*value)\s*[:\-]?\s*(?:@\)?\s*)?{_CUR}{_MONEY}",
    ],
    "premium": [
        rf"(?:has\s+paid|premium\s+(?:of|amount|paid|payable|is))\s*[:\-]?\s*{_CUR}{_MONEY}",
        rf"(?:total\s*premium|premium)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
    "premium_frequency": [
        r"(?:premium\s*(?:frequency|mode)|payment\s*(?:frequency|mode)|mode\s*of\s*payment)\s*[:\-]\s*([A-Za-z ]{4,20})",
    ],
    "start_date": [
        rf"(?:policy\s*period|period\s*of\s*insurance|insurance\s*period)\s*(?:from)?\s*(?:[0-9]{{1,2}}:[0-9]{{2}}\s*hrs?\s*on\s*)?{_DATE}",
        rf"(?:start\s*date|commencement\s*date|date\s*of\s*commencement|effective\s*(?:from|date)|risk\s*(?:start|commencement)\s*date)\s*[:\-]?\s*{_DATE}",
        rf"(?:for\s+)?period\s+of\s*[:\-]?\s*{_DATE}\s*(?:to|upto|up\s*to|-|\u2013)",
    ],
    "expiry_date": [
        rf"(?:policy\s*period|period\s*of\s*insurance|insurance\s*period)\s*(?:from)?\s*(?:[0-9]{{1,2}}:[0-9]{{2}}\s*hrs?\s*on\s*)?{_DATE_NC}\s*(?:to|upto|up\s*to|-|\u2013)\s*(?:[0-9]{{1,2}}:[0-9]{{2}}\s*hrs?\s*on\s*)?{_DATE}",
        rf"(?:expiry\s*date|expiration\s*date|end\s*date|date\s*of\s*expiry|valid\s*(?:up\s*)?to|policy\s*period\s*(?:to|upto|up\s*to)|risk\s*end\s*date)\s*[:\-]?\s*{_DATE}",
        rf"(?:policy\s*period|period\s*of\s*insurance|insurance\s*period)\s*[:\-]?\s*[0-9]{{1,4}}[\-/][0-9]{{1,2}}[\-/][0-9]{{1,4}}\s*(?:to|upto|up\s*to|-|\u2013)\s*{_DATE}",
        rf"(?:for\s+)?period\s+of\s*[:\-]?\s*[0-9]{{1,4}}[\-/][0-9]{{1,2}}[\-/][0-9]{{1,4}}\s*(?:to|upto|up\s*to|-|\u2013)\s*{_DATE}",
    ],
    "renewal_date": [
        rf"(?:renewal\s*date|due\s*date|next\s*renewal|renewal\s*due)\s*[:\-]?\s*{_DATE}",
    ],
    "nominee": [
        r"(?:nominee(?:\s*name)?)\s*[:\-]\s*([A-Za-z .'\-]{3,80})",
    ],
    "tpa": [
        r"(?:tpa|third\s*party\s*administrator)\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80}?)(?:\s{2,}|$|\s+(?:for|on|address|tel|email|location)\b)",
        r"claim\s*administrator\s*[:\-]\s*([A-Za-z0-9 .,&'\-]{3,80}?)(?:\s{2,}|$|\s+(?:for|on|address|tel|email|location)\b)",
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
    # Category-specific extras (extracted only when the document states them).
    "idv": [
        rf"(?:idv|insured\s*declared\s*value)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
    "vehicle_registration_number": [
        r"(?:registration\s*(?:no|number)|vehicle\s*(?:no|number))\s*[:\-]?\s*([A-Z]{2}[ \t\-]?[0-9]{1,2}[ \t\-]?[A-Z]{1,3}[ \t\-]?[0-9]{3,4})",
    ],
    "vehicle_make": [
        r"(?:make|manufacturer)\s*[:\-]\s*([A-Za-z][A-Za-z0-9 .\-]{2,40})",
    ],
    "vehicle_model": [
        r"(?:model)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 .\-]{1,40})",
    ],
    "room_rent_limit": [
        rf"(?:room\s*rent(?:\s*limit)?)\s*[:\-]?\s*{_CUR}{_MONEY}",
    ],
    "co_payment": [
        r"(?:co[\s\-]?payment)\s*[:\-]?\s*([0-9]{1,3}\s*%)",
    ],
    "policy_term": [
        r"(?:policy\s*term|term\s*of\s*the\s*policy)\s*[:\-]?\s*([0-9]+\s*(?:years?|months?))",
    ],
    "destination": [
        r"(?:destination|country\s*of\s*travel)\s*[:\-]\s*([A-Za-z][A-Za-z ,]{2,40})",
    ],
    "property_address": [
        r"(?:property\s*address|address\s*of\s*(?:the\s*)?property)\s*[:\-]\s*([^\n]{5,120})",
    ],
}

# Vocabulary for the insurance category. Counted over the document text; the
# strongest signal wins. Kept deliberately broad so nothing is forced into the
# wrong bucket just because a word is missing.
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    InsuranceCategory.HEALTH.value: (
        "health insurance", "mediclaim", "hospitalisation", "hospitalization",
        "tpa", "cashless", "room rent", "pre-existing", "pre existing",
        "day care", "floater", "sum insured", "hospital", "surgery",
        "in-patient", "opd", "critical illness", "restoration",
    ),
    InsuranceCategory.LIFE.value: (
        "life insurance", "term plan", "sum assured", "death benefit",
        "maturity", "endowment", "jeevan", "ulip", "annuity", "policy term",
        "nominee", "life assured",
    ),
    InsuranceCategory.MOTOR.value: (
        "motor insurance", "vehicle", "car insurance", "private car",
        "package policy", "registration number", "idv", "two wheeler",
        "bike", "own damage", "third party", "no claim bonus",
    ),
    InsuranceCategory.PROPERTY.value: (
        "home insurance", "household", "property insurance", "fire insurance",
        "building", "contents cover", "burglary", "shop insurance",
    ),
    InsuranceCategory.TRAVEL.value: (
        "travel insurance", "trip", "baggage", "flight delay",
        "overseas", "travel delay", "trip cancellation", "schengen",
    ),
    InsuranceCategory.PERSONAL_ACCIDENT.value: (
        "personal accident", "accidental death", "disability", "accident cover",
    ),
    InsuranceCategory.BUSINESS.value: (
        "commercial insurance", "business insurance", "liability",
        "business interruption", "employer liability",
    ),
    InsuranceCategory.AGRICULTURE.value: (
        "crop insurance", "livestock", "agriculture", "weather insurance",
    ),
    InsuranceCategory.MARINE.value: (
        "marine insurance", "cargo", "hull", "freight",
    ),
    InsuranceCategory.CYBER.value: (
        "cyber insurance", "cyber liability", "data breach",
    ),
}

# Policy "type" (subtype) vocabulary per category, with the phrases that
# indicate it. Only used to pick a label; the document's own words are kept.
_POLICY_TYPE_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    InsuranceCategory.HEALTH.value: {
        "family_floater": ("family floater", "floater", "family health"),
        "individual": ("individual health", "individual mediclaim"),
        "group_employer": ("group health", "group mediclaim", "employer"),
        "critical_illness": ("critical illness",),
        "senior_citizen": ("senior citizen",),
        "maternity": ("maternity",),
        "top_up": ("top up", "top-up", "super top"),
    },
    InsuranceCategory.LIFE.value: {
        "term": ("term plan", "term insurance", "pure term"),
        "endowment": ("endowment",),
        "ulip": ("unit linked", "ulip"),
        "whole_life": ("whole life",),
        "money_back": ("money back",),
        "annuity": ("annuity", "pension"),
        "group_life": ("group life",),
    },
    InsuranceCategory.MOTOR.value: {
        "car": ("private car", "car", "four wheeler"),
        "two_wheeler": ("two wheeler", "two-wheeler", "motor cycle",
                        "motorcycle", "scooter", "bike"),
        "commercial_vehicle": ("commercial vehicle", "goods carrying", "taxi"),
    },
    InsuranceCategory.TRAVEL.value: {
        "international": ("international", "overseas", "schengen", "worldwide"),
        "domestic": ("domestic",),
        "student": ("student travel", "student"),
    },
    InsuranceCategory.PROPERTY.value: {
        "home": ("home insurance", "residence", "dwelling"),
        "household_contents": ("household contents", "contents"),
        "fire": ("fire insurance", "standard fire"),
    },
    InsuranceCategory.PERSONAL_ACCIDENT.value: {
        "group": ("group personal accident", "group accident"),
        "individual": ("individual personal accident",),
    },
}

# Document-class signals, strongest first. The order matters: a claim document
# that mentions a policy number must still be classified as a claim.
_DOCUMENT_CLASS_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (DocumentClass.CLAIM_DOCUMENT.value, (
        "claim form", "claim settlement", "claim intimation", "discharge voucher",
        "claim reference", "claim number", "reimbursement claim",
    )),
    (DocumentClass.PREMIUM_RECEIPT.value, (
        "premium receipt", "received with thanks", "e-receipt", "tax invoice",
        "acknowledgement of premium", "section 80d",
    )),
    (DocumentClass.POLICY_SCHEDULE.value, (
        "policy schedule", "schedule of insurance", "schedule of cover",
        "policy particulars", "schedule of the policy",
    )),
    (DocumentClass.POLICY_CERTIFICATE.value, (
        "certificate of insurance", "policy certificate", "this is to certify",
    )),
    (DocumentClass.RENEWAL_DOCUMENT.value, (
        "renewal notice", "renewal of your", "renewal premium", "due for renewal",
    )),
    (DocumentClass.ENDORSEMENT.value, (
        "endorsement", "amendment to the policy", "policy amendment",
    )),
    (DocumentClass.POLICY_WORDING.value, (
        "policy wording", "terms and conditions", "general conditions",
        "definitions and exclusions",
    )),
    (DocumentClass.PROPOSAL_DOCUMENT.value, (
        "proposal form", "proposal for insurance", "application form",
    )),
]

# Phrases that mark a document as plainly not insurance.
_NON_INSURANCE_HINTS = (
    "invoice", "purchase order", "boarding pass", "salary slip",
    "rent agreement", "electricity bill", "menu", "recipe", "resume",
    "curriculum vitae", "lecture notes",
)
_INSURANCE_HINTS = (
    "insurance", "policy", "insured", "insurer", "premium", "sum insured",
    "sum assured", "coverage", "claim", "renewal", "nominee",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")

_SALUTATION = re.compile(r"\s+(?:mr|mrs|ms|shri|smt|dr)\.?\s+", re.IGNORECASE)
_NAME_STOP = re.compile(
    r"\s+(?:has\s+paid|issued|for\s+period|towards|is\s+issued|contact|email|"
    r"policy|welcome|please|and\s+zero|rupees)\b",
    re.IGNORECASE,
)
_LABEL_STOP = re.compile(
    r"\s+(?:relationship|date\s+of\s+birth|member|particulars|policy\s+holder|"
    r"policyholder|nominee|address|contact|email|tel|age|gender|sum\s+insured|"
    r"base\s+sum|multiplier|plan|rider)\b",
    re.IGNORECASE,
)

# A new policy boundary inside a bundle. Deliberately conservative: we look for
# a policy-number label or an explicit schedule/policy heading that also names
# a policy number nearby.
_POLICY_BOUNDARY = re.compile(
    r"(?:policy\s*(?:no|number)\s*[:\-#]|policy\s*schedule|schedule\s*of\s*(?:insurance|cover)|"
    r"certificate\s*of\s*insurance|policy\s*certificate)",
    re.IGNORECASE,
)
_CLAIM_STRONG = re.compile(
    r"(?:claim\s*form|claim\s*intimation|discharge\s*voucher|claim\s*settlement)",
    re.IGNORECASE,
)


def _clean_name(value: str) -> str:
    """Trim a captured person/company name of salutations, labels and prose."""
    value = _SALUTATION.split(value)[0]
    value = _LABEL_STOP.split(value)[0]
    value = _NAME_STOP.split(value)[0]
    value = re.sub(r"^(?:mr|mrs|ms|shri|smt|dr)\.?\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" .,-:")


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    return [p for p in parts if len(p) > 15]


def _tokenize(text: str) -> list[str]:
    return tokenize(text)


def _keyword_score(text: str, hints: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(lowered.count(hint) for hint in hints)


class NullProvider(AIProvider):
    name = "null"

    @property
    def embedding_model(self) -> str:
        return f"local-hash-{EMBEDDING_DIM}"

    async def classify_document(self, text: str) -> str:
        """Coarse hint used by the legacy pipeline: policy / claim / other."""
        document_class, _ = self.classify_document_class(text)
        # A strong claim signal wins even when a policy number is also present,
        # because a claim document legitimately quotes its policy number.
        if document_class == DocumentClass.CLAIM_DOCUMENT.value or _CLAIM_STRONG.search(text):
            return "claim"
        if document_class in {
            DocumentClass.NON_INSURANCE_DOCUMENT.value,
            DocumentClass.UNKNOWN.value,
        }:
            return "other"
        if document_class in POLICY_BEARING_CLASSES:
            return "policy"
        return "other"

    def classify_document_class(self, text: str) -> tuple[str, float]:
        """Determine what the document is, with a confidence.

        Never claims certainty: confidence reflects how many signals matched.
        """
        lowered = text.lower()
        insurance_hits = _keyword_score(text, _INSURANCE_HINTS)
        non_insurance_hits = _keyword_score(text, _NON_INSURANCE_HINTS)

        if insurance_hits == 0:
            if non_insurance_hits > 0:
                return DocumentClass.NON_INSURANCE_DOCUMENT.value, 0.7
            return DocumentClass.UNKNOWN.value, 0.3

        for doc_class, hints in _DOCUMENT_CLASS_HINTS:
            hits = _keyword_score(text, hints)
            if hits > 0:
                confidence = min(0.95, 0.6 + 0.1 * hits)
                return doc_class, confidence

        # A policy number plus insurance vocabulary is an insurance policy.
        if "policy" in lowered and ("policy no" in lowered or "policy number" in lowered):
            return DocumentClass.INSURANCE_POLICY.value, 0.85
        if insurance_hits >= 3:
            return DocumentClass.INSURANCE_POLICY.value, 0.75
        return DocumentClass.OTHER_INSURANCE_DOCUMENT.value, 0.5

    async def classify_insurance(self, text: str) -> tuple[str, float]:
        return self.classify_category(text)

    def classify_category(self, text: str) -> tuple[str, float]:
        """Return ``(category, confidence)`` inferred from the document text."""
        scores = {
            category: _keyword_score(text, hints)
            for category, hints in _CATEGORY_HINTS.items()
        }
        best = max(scores, key=lambda k: scores[k])
        total = sum(scores.values())
        if scores[best] == 0 or total == 0:
            return InsuranceCategory.OTHER.value, 0.0
        confidence = min(0.97, scores[best] / total)
        # A single weak signal should not read as near-certain.
        confidence = round(min(0.97, 0.5 + 0.5 * confidence), 2)
        return best, confidence

    def classify_policy_type(
        self, text: str, category: str
    ) -> tuple[str, float, str | None, float]:
        """Return ``(policy_type, type_conf, subtype, subtype_conf)``.

        ``policy_type`` is the coverage style (e.g. family floater, car);
        ``subtype`` refines motor cover (comprehensive / third party).
        """
        lowered = text.lower()
        hints = _POLICY_TYPE_HINTS.get(category, {})
        for policy_type, phrases in hints.items():
            hits = sum(lowered.count(p) for p in phrases)
            if hits:
                conf = min(0.95, 0.6 + 0.15 * hits)
                subtype = None
                subtype_conf = 0.0
                if category == InsuranceCategory.MOTOR.value:
                    if "comprehensive" in lowered:
                        subtype, subtype_conf = "comprehensive", 0.9
                    elif "third party" in lowered or "third-party" in lowered:
                        subtype, subtype_conf = "third_party", 0.85
                return policy_type, conf, subtype, subtype_conf
        return "other", 0.0, None, 0.0

    async def extract_policy(self, text: str) -> list[ExtractedField]:
        """Legacy contract: a flat list of fields with a ``found`` flag."""
        return [
            ExtractedField(
                field_name=f.field_name,
                value=f.value,
                confidence=f.confidence,
                source_page=f.source_page,
                found=f.evidence != "not_found" and f.value is not None,
            )
            for f in _extract_fields(text)
        ]

    async def extract_candidates(
        self, text: str, *, page_count: int | None = None
    ) -> list[PolicyCandidate]:
        """Segment the document into one or more policy candidates.

        A single-policy document yields one candidate. A bundle holding several
        policies is split on policy boundaries so information from different
        policies is never mixed.
        """
        segments = _segment_policies(text)
        candidates: list[PolicyCandidate] = []
        for index, (segment_text, page_start, page_end) in enumerate(segments):
            if not segment_text.strip():
                continue
            category, category_conf = self.classify_category(segment_text)
            policy_type, type_conf, subtype, subtype_conf = self.classify_policy_type(
                segment_text, category
            )
            page_offset = (page_start or 1) - 1
            fields = _extract_fields(segment_text, page_offset=page_offset)
            candidates.append(
                PolicyCandidate(
                    category=category,
                    category_confidence=category_conf,
                    policy_type=valid_policy_type(category, policy_type),
                    policy_type_confidence=type_conf,
                    policy_subtype=subtype,
                    policy_subtype_confidence=subtype_conf,
                    page_start=page_start,
                    page_end=page_end,
                    fields=fields,
                    category_data=_category_extras(fields, category),
                )
            )
        if not candidates:
            # Never return nothing for readable insurance text: fall back to a
            # single candidate so the user still sees what was found.
            category, category_conf = self.classify_category(text)
            policy_type, type_conf, subtype, subtype_conf = self.classify_policy_type(
                text, category
            )
            fields = _extract_fields(text)
            candidates.append(
                PolicyCandidate(
                    category=category,
                    category_confidence=category_conf,
                    policy_type=valid_policy_type(category, policy_type),
                    policy_type_confidence=type_conf,
                    policy_subtype=subtype,
                    policy_subtype_confidence=subtype_conf,
                    fields=fields,
                    category_data=_category_extras(fields, category),
                )
            )
        return candidates

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
        ordered = [s for s in sentences if s in set(ranked)]
        return " ".join(ordered)[:1200]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(t) for t in texts]


def _search_with_page(
    text: str, patterns: list[str]
) -> tuple[str | None, int | None, str | None]:
    """Search patterns across the whole text, tracking page and source line.

    Page numbers are approximated by counting form-feed characters used as
    page separators during text extraction. The matched line is returned as
    ``source_text`` so the UI can show where a value came from.
    """
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            page = text[: match.start(1)].count("\f") + 1
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end == -1:
                line_end = len(text)
            source_text = _normalize(text[line_start:line_end].strip())[:300]
            return match.group(1), page, source_text
    return None, None, None


def _extract_fields(text: str, page_offset: int = 0) -> list[CandidateField]:
    """Extract every known field, marking absent ones as not found.

    ``page_offset`` shifts reported page numbers so a field extracted from a
    later segment of a bundle cites its real page, not the segment-relative one.
    """
    fields: list[CandidateField] = []
    for name, patterns in _FIELD_PATTERNS.items():
        match, page, source_text = _search_with_page(text, patterns)
        if match:
            value = _normalize(match.strip())
            if name in {"policyholder_name", "nominee", "vehicle_make", "vehicle_model"}:
                value = _clean_name(value)
            if value:
                fields.append(
                    CandidateField(
                        field_name=name,
                        value=value,
                        confidence=0.7,
                        source_page=(page + page_offset) if page else None,
                        source_text=source_text,
                        evidence="explicitly_found",
                    )
                )
                continue
        fields.append(
            CandidateField(
                field_name=name,
                value=None,
                confidence=0.0,
                source_page=None,
                source_text=None,
                evidence="not_found",
            )
        )
    return fields


def _category_extras(
    fields: list[CandidateField], category: str
) -> dict[str, str]:
    """Collect category-specific values that were actually found.

    Only explicitly-found values are included; nothing is invented and no
    universal field is duplicated here.
    """
    universal = set(UNIVERSAL_FIELDS)
    profile = set(fields_for_category(category))
    extras: dict[str, str] = {}
    for f in fields:
        if f.value and f.field_name not in universal and f.field_name in profile:
            extras[f.field_name] = f.value
    return extras


def _segment_policies(text: str) -> list[tuple[str, int | None, int | None]]:
    """Split text into policy segments with their page ranges.

    Single-policy documents return one segment covering the whole text. A
    bundle is split only when the policy boundary is corroborated by a policy
    number or a strong document heading, so a page that merely mentions
    "policy" is not treated as a new policy.
    """
    pages = text.split("\f")
    total_pages = len(pages)

    # Locate boundaries: a page that starts a new policy. We look at page
    # granularity because that is what we can cite as a source range.
    boundaries: list[int] = []
    for index, page in enumerate(pages):
        if index == 0:
            boundaries.append(0)
            continue
        has_boundary = bool(_POLICY_BOUNDARY.search(page))
        # A boundary must also carry its own policy number, otherwise it is a
        # continuation of the same policy.
        has_number = bool(
            re.search(r"policy\s*(?:no|number)\s*[:\-#]?\s*[A-Za-z0-9]", page, re.I)
        )
        if has_boundary and has_number:
            boundaries.append(index)

    if len(boundaries) <= 1:
        # One policy (or none detected) — the whole document is one candidate.
        return [(text, 1 if total_pages else None, total_pages or None)]

    segments: list[tuple[str, int | None, int | None]] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else total_pages - 1
        segment_text = "\f".join(pages[start : end + 1])
        segments.append((segment_text, start + 1, end + 1))
    return segments


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


# Re-exported for the OpenAI provider, which reuses the deterministic
# extraction as its fallback.
__all__ = [
    "NullProvider",
    "_FIELD_PATTERNS",
    "_search_with_page",
    "_normalize",
    "_clean_name",
    "category_for_policy_type",
    "CATEGORY_TO_POLICY_TYPE",
    "POLICY_TYPES_BY_CATEGORY",
]
