"""Offline optical character recognition for images and scanned PDF pages.

The engine is RapidOCR, which runs ONNX models locally: no document ever
leaves the machine and no network call is made. It is an optional dependency
(``pip install -e ".[ocr]"``); when it is absent the application reports that
OCR is unavailable instead of fabricating text.

Nothing here is eager: importing this module is cheap and the model is loaded
on the first OCR request only.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger("koverly.ocr")

_engine: Any = None
_engine_lock = threading.Lock()


class OCRUnavailableError(Exception):
    """OCR was requested but no engine is installed or enabled."""


class OCRProcessingError(Exception):
    """The image could not be decoded or OCR failed unexpectedly."""


def _module_available() -> bool:
    try:
        return importlib.util.find_spec("rapidocr_onnxruntime") is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


def _backend_mode() -> str:
    return settings.OCR_BACKEND.strip().lower()


def ocr_backend_name() -> str:
    """Resolved backend: ``rapidocr``, ``none``, or ``unavailable``."""
    if _backend_mode() in {"none", "off", "disabled"}:
        return "none"
    return "rapidocr" if _module_available() else "unavailable"


def is_ocr_available() -> bool:
    return ocr_backend_name() == "rapidocr"


def unavailable_message() -> str:
    if ocr_backend_name() == "none":
        return (
            "Image OCR is disabled (OCR_BACKEND=none). Enable it to read "
            "images and scanned PDFs."
        )
    return (
        "Image OCR is not available. Install the optional OCR dependencies "
        'with `pip install -e ".[ocr]"` to read images and scanned PDFs.'
    )


def _get_engine() -> Any:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        backend = ocr_backend_name()
        if backend == "none":
            raise OCRUnavailableError(unavailable_message())
        if backend != "rapidocr":
            raise OCRUnavailableError(unavailable_message())

        # Imported lazily so the API starts quickly without the OCR extra.
        from rapidocr_onnxruntime import RapidOCR

        logger.info(
            "ocr_engine_initialized",
            extra={"extra_fields": {"backend": "rapidocr"}},
        )
        _engine = RapidOCR()
        return _engine


def _prepare_image(data: bytes) -> bytes:
    """Validate, auto-orient, and normalise an image to PNG bytes.

    Decoding here (rather than passing raw bytes to the engine) means corrupt
    uploads fail with a clear message instead of an obscure backend error, and
    EXIF-rotated phone photos are read the right way up.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise OCRUnavailableError(unavailable_message()) from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            rgb = image.convert("RGB")
            buffer = io.BytesIO()
            rgb.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as exc:
        raise OCRProcessingError(
            "Image OCR could not read this file. Upload a valid JPG or PNG "
            "image, or a text-based PDF."
        ) from exc


def _reading_order(result: list) -> list[tuple[float, float, str]]:
    """Return detected lines sorted top-to-bottom, left-to-right."""
    lines: list[tuple[float, float, str]] = []
    for item in result:
        try:
            box, text, score = item
            confidence = float(score)
        except (TypeError, ValueError):
            continue
        text = str(text).strip()
        if not text or confidence < settings.OCR_MIN_CONFIDENCE:
            continue
        try:
            top = min(float(point[1]) for point in box)
            left = min(float(point[0]) for point in box)
        except (TypeError, ValueError, IndexError):
            top, left = float(len(lines)), 0.0
        lines.append((top, left, text))
    lines.sort(key=lambda line: (round(line[0] / 8), line[1]))
    return lines


def ocr_image(data: bytes) -> str:
    """Extract text from image bytes, preserving approximate line breaks."""
    engine = _get_engine()
    prepared = _prepare_image(data)
    try:
        result, _elapsed = engine(prepared)
    except Exception as exc:
        raise OCRProcessingError(
            "Image OCR failed while reading this file. Try a clearer scan or "
            "a text-based PDF."
        ) from exc
    if not result:
        return ""
    return "\n".join(text for _, _, text in _reading_order(result))
