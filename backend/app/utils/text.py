"""Shared text tokenisation helpers.

Kept dependency-free and identical across the AI provider and retrieval
service so lexical fallback scoring agrees with embedding-based scoring.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric token list."""
    return _WORD_RE.findall(text.lower())


def lexical_overlap(query: str, text: str) -> float:
    """Fraction of distinct query tokens present in ``text`` (0.0–1.0)."""
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return 0.0
    return len(q_tokens & set(tokenize(text))) / len(q_tokens)
