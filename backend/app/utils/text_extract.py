"""Document text extraction.

PDFs are parsed with pypdf; pages that have no text layer (scanned cover pages,
signatures, image-only schedules) are rendered and OCR'd with self-hosted
Tesseract. Page boundaries are preserved using form-feed characters so
downstream extraction can report a source page.

OCR is best-effort and never fabricates: if the engine or its system
dependencies are missing, or OCR yields nothing, the document fails with an
explicit reason rather than silently producing empty or invented text.
"""

from __future__ import annotations

import io
import logging
import shutil

from app.core.config import settings

logger = logging.getLogger("koverly.text_extract")


class TextExtractionError(Exception):
    pass


def ocr_available() -> bool:
    """True when OCR is enabled and both the binary and Python deps exist."""
    if not settings.OCR_ENABLED:
        return False
    if not (settings.TESSERACT_CMD or shutil.which("tesseract")):
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _configure_tesseract(pytesseract) -> None:
    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


def _ocr_image(image) -> str:
    import pytesseract

    _configure_tesseract(pytesseract)
    try:
        return pytesseract.image_to_string(
            image,
            lang=settings.OCR_LANGUAGES,
            timeout=settings.OCR_PAGE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - one page must not fail the whole doc
        logger.warning("ocr_page_failed error=%s", exc)
        return ""


def _ocr_images(data: bytes) -> str:
    """OCR a single uploaded image (JPG/PNG)."""
    if not ocr_available():
        raise TextExtractionError(
            "Image OCR is not available on this server. Please upload a "
            "text-based PDF or enter the details manually."
        )
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise TextExtractionError("Image support is not installed.") from exc

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise TextExtractionError("Could not read the image file.") from exc

    text = _ocr_image(image)
    if not text.strip():
        raise TextExtractionError(
            "No readable text was found in this image. Please upload a clearer "
            "copy or enter the details manually."
        )
    return text


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Return ``(text_with_page_breaks, page_count)``.

    Pages with a usable text layer are read directly; pages without one are
    OCR'd when OCR is available.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise TextExtractionError("PDF support is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise TextExtractionError("Could not read the PDF file.") from exc

    page_count = len(reader.pages)
    native: list[str] = []
    for page in reader.pages:
        try:
            native.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page shouldn't fail all
            native.append("")

    need_ocr = [
        i
        for i, text in enumerate(native)
        if len(text.strip()) < settings.OCR_MIN_TEXT_CHARS
    ]

    if need_ocr:
        ocr_pages = _ocr_pdf_pages(data, need_ocr, page_count)
        for index, text in ocr_pages.items():
            native[index] = text

    # If nothing at all was readable, fail with a clear reason instead of
    # returning empty text that would look like a successful extraction.
    if not any(t.strip() for t in native):
        if settings.OCR_ENABLED:
            raise TextExtractionError(
                "No readable text was found in this PDF, even after OCR. "
                "Please upload a clearer copy or enter the details manually."
            )
        raise TextExtractionError(
            "No readable text was found in this PDF. It looks like a scanned "
            "document; please upload a text-based PDF or enter the details "
            "manually."
        )

    return "\f".join(native), page_count


def _ocr_pdf_pages(
    data: bytes, page_indexes: list[int], page_count: int
) -> dict[int, str]:
    """OCR the given 0-based page indexes. Returns ``{index: text}``."""
    if not settings.OCR_ENABLED:
        return {}
    if not ocr_available():
        logger.info(
            "ocr_unavailable pages=%s page_count=%s", len(page_indexes), page_count
        )
        return {}

    try:
        import pdf2image
    except ImportError:
        logger.info("ocr_unavailable reason=pdf2image_missing")
        return {}

    # OCR is bounded: never render more than OCR_MAX_PAGES pages.
    targets = sorted(page_indexes)[: settings.OCR_MAX_PAGES]
    if len(page_indexes) > settings.OCR_MAX_PAGES:
        logger.info(
            "ocr_page_limit_reached requested=%s limit=%s",
            len(page_indexes),
            settings.OCR_MAX_PAGES,
        )

    # Render in contiguous batches so a single conversion call covers a run of
    # scanned pages (pdftoppm's first_page/last_page are inclusive).
    results: dict[int, str] = {}
    batch_start = targets[0]
    batch_end = targets[0]
    batches: list[tuple[int, int]] = []
    for index in targets[1:]:
        if index == batch_end + 1:
            batch_end = index
        else:
            batches.append((batch_start, batch_end))
            batch_start = batch_end = index
    batches.append((batch_start, batch_end))

    for first, last in batches:
        try:
            images = pdf2image.convert_from_bytes(
                data,
                dpi=settings.OCR_DPI,
                fmt="png",
                first_page=first + 1,
                last_page=last + 1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ocr_render_failed pages=%s-%s error=%s", first, last, exc)
            continue
        for offset, image in enumerate(images):
            results[first + offset] = _ocr_image(image)
    return results


def extract_text(data: bytes, content_type: str) -> tuple[str, int | None]:
    if content_type == "application/pdf":
        return extract_pdf_text(data)
    if content_type in {"image/jpeg", "image/png"}:
        return _ocr_images(data), None
    raise TextExtractionError("Unsupported document type for text extraction.")

