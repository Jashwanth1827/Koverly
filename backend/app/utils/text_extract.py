"""Document text extraction.

PDFs are parsed with pypdf; page boundaries are preserved using form-feed
characters so downstream extraction can report a source page.

Image OCR is intentionally *not* faked: if no OCR engine is configured the
document is marked FAILED with an explicit reason rather than silently
producing empty or invented text.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger("koverly.text_extract")


class TextExtractionError(Exception):
    pass


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Return ``(text_with_page_breaks, page_count)``."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise TextExtractionError("PDF support is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page shouldn't fail all
                pages.append("")
        text = "\f".join(pages)
        return text, len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise TextExtractionError("Could not read the PDF file.") from exc


def extract_text(data: bytes, content_type: str) -> tuple[str, int | None]:
    if content_type == "application/pdf":
        return extract_pdf_text(data)
    if content_type in {"image/jpeg", "image/png"}:
        raise TextExtractionError(
            "Image OCR is not configured. Text could not be extracted from "
            "this image; please upload a text-based PDF or enter details "
            "manually."
        )
    raise TextExtractionError("Unsupported document type for text extraction.")
