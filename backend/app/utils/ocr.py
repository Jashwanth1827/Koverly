"""OCR availability reporting for the runtime config endpoint.

The extraction pipeline itself lives in ``app/utils/text_extract.py``
(self-hosted Tesseract). This module only exposes availability/backend
information so ``/api/v1/config`` can report the real state without
importing engine internals.
"""

from __future__ import annotations

from app.core.config import settings
from app.utils.text_extract import ocr_available


def ocr_backend_name() -> str:
    if not settings.OCR_ENABLED:
        return "disabled"
    return "tesseract" if ocr_available() else "unavailable"


def is_ocr_available() -> bool:
    return bool(settings.OCR_ENABLED) and ocr_available()
