"""Real-policy corpus regression tests.

Fixtures live in tests/corpus/*.txt with matching *.json of expected values.
PII must be redacted before committing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.ai.null_provider import NullProvider

CORPUS = Path(__file__).parent / "corpus"


def test_corpus_fixtures_extract():
    provider = NullProvider()
    txt_files = sorted(CORPUS.glob("*.txt"))
    assert txt_files, "Add at least one sanitized policy fixture to tests/corpus/"
    for txt in txt_files:
        expected_path = txt.with_suffix(".json")
        if not expected_path.exists():
            continue
        text = txt.read_text(encoding="utf-8")
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        by_name = {f.field_name: f for f in asyncio.run(provider.extract_policy(text))}
        for key, want in expected.items():
            field = by_name[key]
            assert field.found, f"{txt.name}: {key} not found"
            assert field.value == want, f"{txt.name}: {key} {field.value!r} != {want!r}"
