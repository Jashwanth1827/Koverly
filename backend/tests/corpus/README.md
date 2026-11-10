# Extraction corpus

Real-policy regression fixtures live here (sanitized). Each fixture contains
plaintext extracted from a real policy document with PII redacted, plus an
expected JSON of fields that must be found.

Naming: `insurer_type.ext.txt` or just descriptive names. Keep raw PDFs out
of git if they contain sensitive data; prefer sanitized text fixtures.

Add a new fixture when a real policy extracts poorly. Run:
`pytest tests/test_corpus_extraction.py -v`
