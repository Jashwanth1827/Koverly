"""Document text extraction — provider/adapter architecture.

The rest of the application depends on one function, ``extract_text``, not on
any particular library. Each format has its own processor, so adding a format
(or swapping a library) never touches the pipeline:

    DocumentProcessor
    ├── PDFProcessor    (pypdf; OCR fallback for scanned pages)
    ├── ImageProcessor  (JPG/PNG/WEBP via Pillow + Tesseract)
    ├── WordProcessor   (DOCX via python-docx, DOC via OLE text scan)
    └── TextProcessor   (TXT and RTF)

Page boundaries are preserved with form-feed characters so downstream
extraction can report a source page. OCR is best-effort and never fabricates:
if the engine is missing or yields nothing, the document fails with an
explicit reason rather than silently producing empty or invented text.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("koverly.text_extract")

# Everything the backend can safely read. Kept in one place so upload
# validation, storage sniffing, and the processors cannot drift apart.
PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DOC_TYPES = {"application/msword"}
RTF_TYPES = {"application/rtf", "text/rtf"}
TEXT_TYPES = {"text/plain"}

SUPPORTED_CONTENT_TYPES = (
    PDF_TYPES | IMAGE_TYPES | DOCX_TYPES | DOC_TYPES | RTF_TYPES | TEXT_TYPES
)

TEXT_DOCUMENT = "text_document"
SCANNED_DOCUMENT = "scanned_document"
IMAGE_DOCUMENT = "image_document"

_MAX_TEXT_CHARS = 400_000


class TextExtractionError(Exception):
    pass


@dataclass
class TextResult:
    """Extracted text plus how it was obtained."""

    text: str
    page_count: int | None
    source_kind: str
    ocr_used: bool = False


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


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _extract_pdf(data: bytes) -> TextResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise TextExtractionError("PDF support is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise TextExtractionError(
            "We couldn't read this document. Please upload another copy."
        ) from exc

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
    ocr_used = False
    if need_ocr:
        ocr_pages = _ocr_pdf_pages(data, need_ocr, page_count)
        if ocr_pages:
            ocr_used = True
        for index, text in ocr_pages.items():
            native[index] = text

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

    # A PDF whose pages were mostly read by OCR is a scanned document.
    mostly_ocr = ocr_used and len(need_ocr) >= max(1, page_count // 2)
    return TextResult(
        text=_truncate("\f".join(native)),
        page_count=page_count,
        source_kind=SCANNED_DOCUMENT if mostly_ocr else TEXT_DOCUMENT,
        ocr_used=ocr_used,
    )


def _ocr_pdf_pages(
    data: bytes, page_indexes: list[int], page_count: int
) -> dict[int, str]:
    """OCR the given 0-based page indexes. Returns ``{index: text}``."""
    if not settings.OCR_ENABLED or not ocr_available():
        logger.info(
            "ocr_unavailable pages=%s page_count=%s", len(page_indexes), page_count
        )
        return {}

    try:
        import pdf2image
    except ImportError:
        logger.info("ocr_unavailable reason=pdf2image_missing")
        return {}

    targets = sorted(page_indexes)[: settings.OCR_MAX_PAGES]
    if len(page_indexes) > settings.OCR_MAX_PAGES:
        logger.info(
            "ocr_page_limit_reached requested=%s limit=%s",
            len(page_indexes),
            settings.OCR_MAX_PAGES,
        )

    results: dict[int, str] = {}
    batch_start = batch_end = targets[0]
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


# --------------------------------------------------------------------------- #
# Images (JPG / PNG / WEBP)
# --------------------------------------------------------------------------- #
def _extract_image(data: bytes) -> TextResult:
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
        raise TextExtractionError(
            "We couldn't read this document. Please upload another copy."
        ) from exc

    text = _ocr_image(image)
    if not text.strip():
        raise TextExtractionError(
            "No readable text was found in this image. Please upload a clearer "
            "copy or enter the details manually."
        )
    return TextResult(
        text=_truncate(text), page_count=1, source_kind=IMAGE_DOCUMENT, ocr_used=True
    )


# --------------------------------------------------------------------------- #
# Word
# --------------------------------------------------------------------------- #
def _extract_docx(data: bytes) -> TextResult:
    """Read a DOCX without a hard dependency on python-docx.

    A DOCX is a ZIP of XML. We read ``word/document.xml`` and split paragraphs,
    which covers the overwhelming majority of policy documents. If
    ``python-docx`` is installed we prefer it (better structure handling).
    """
    try:
        import docx  # type: ignore

        document = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in document.paragraphs)
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    text += "\n" + " : ".join(cells)
        if text.strip():
            return TextResult(
                text=_truncate(text), page_count=None, source_kind=TEXT_DOCUMENT
            )
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.info("python_docx_failed falling back to xml parse: %s", exc)

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        raise TextExtractionError(
            "We couldn't read this document. Please upload another copy."
        ) from exc

    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    text = _unescape_xml(re.sub(r"<[^>]+>", "", xml))
    if not text.strip():
        raise TextExtractionError(
            "We couldn't read any text from this Word document. Please upload "
            "another copy or enter the details manually."
        )
    return TextResult(text=_truncate(text), page_count=None, source_kind=TEXT_DOCUMENT)


def _extract_doc(data: bytes) -> TextResult:
    """Best-effort text recovery from a legacy binary .doc (OLE) file.

    There is no pure-Python .doc parser. We scan the OLE stream for runs of
    printable text, which recovers policy text in practice. If nothing usable
    is found we fail explicitly rather than pretending the document was read.
    """
    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if len(current) >= 12:
            chunks.append("".join(current))
        current.clear()

    for byte in data:
        ch = chr(byte)
        if ch in "\r\n\t" or 32 <= byte < 127:
            current.append("\n" if ch in "\r\n" else ch)
        elif byte in (0x82, 0x85, 0x91, 0x92, 0x93, 0x94, 0x96, 0x97):
            current.append(
                {
                    0x82: "‚", 0x85: "…", 0x91: "‘", 0x92: "’",
                    0x93: "“", 0x94: "”", 0x96: "–", 0x97: "—",
                }[byte]
            )
        else:
            flush()
    flush()

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(chunks)).strip()
    if len(text) < 40:
        raise TextExtractionError(
            "We couldn't read this Word document. Please save it as a PDF and "
            "upload that, or enter the details manually."
        )
    return TextResult(text=_truncate(text), page_count=None, source_kind=TEXT_DOCUMENT)


def _extract_rtf(data: bytes) -> TextResult:
    raw = data.decode("latin-1", "ignore")
    try:
        from striprtf.striprtf import rtf_to_text  # type: ignore

        text = rtf_to_text(raw)
    except ImportError:
        text = _strip_rtf_manually(raw)
    if not text.strip():
        raise TextExtractionError(
            "We couldn't read any text from this document. Please upload "
            "another copy or enter the details manually."
        )
    return TextResult(text=_truncate(text), page_count=None, source_kind=TEXT_DOCUMENT)


def _strip_rtf_manually(raw: str) -> str:
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    text = re.sub(r"[{}]", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def _extract_plain_text(data: bytes) -> TextResult:
    text = ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text.strip():
        raise TextExtractionError(
            "We couldn't read any text from this document. Please upload "
            "another copy or enter the details manually."
        )
    return TextResult(text=_truncate(text), page_count=None, source_kind=TEXT_DOCUMENT)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def _truncate(text: str) -> str:
    return text[:_MAX_TEXT_CHARS]


def _unescape_xml(text: str) -> str:
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def extract_text(data: bytes, content_type: str) -> TextResult:
    """Extract text from any supported document. Never fabricates content."""
    if content_type in PDF_TYPES:
        return _extract_pdf(data)
    if content_type in IMAGE_TYPES:
        return _extract_image(data)
    if content_type in DOCX_TYPES:
        return _extract_docx(data)
    if content_type in DOC_TYPES:
        return _extract_doc(data)
    if content_type in RTF_TYPES:
        return _extract_rtf(data)
    if content_type in TEXT_TYPES:
        return _extract_plain_text(data)
    raise TextExtractionError(
        "This file type isn't supported. Please upload a PDF, image, Word, "
        "text, or scanned document."
    )
