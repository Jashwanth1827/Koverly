"""Document text extraction.

Supported inputs:

* **PDF** - parsed directly; scanned pages fall back to OCR when available.
* **Images (JPG/PNG)** - read with the OCR engine.
* **Word (.docx)** - paragraphs and tables read with ``python-docx``.
* **Excel (.xlsx/.xls)** - every sheet read row by row with ``openpyxl`` /
  ``xlrd``.
* **Text (.md/.csv/.txt)** - decoded directly.

Page boundaries are preserved using form-feed characters so downstream
extraction can report a source page. For spreadsheets each sheet becomes a
page; for Word documents the whole file is a single page.

OCR is never faked: if no engine is available the document fails with an
explicit reason rather than producing empty or invented text.
"""

from __future__ import annotations

import csv
import io
import logging

from app.core.config import settings
from app.utils.ocr import (
    OCRProcessingError,
    OCRUnavailableError,
    is_ocr_available,
    ocr_image,
    unavailable_message,
)

logger = logging.getLogger("koverly.text_extract")


class TextExtractionError(Exception):
    pass


def _clean_text(text: str) -> str:
    # Normalise MuPDF's layout spacing without destroying line structure.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _extract_pdf_pages_pypdf(data: bytes) -> tuple[list[str], int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise TextExtractionError("PDF support is not installed.") from exc

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(_clean_text(page.extract_text() or ""))
        except Exception:  # noqa: BLE001 - one bad page shouldn't fail all
            pages.append("")
    return pages, len(reader.pages)


def _ocr_pdf_scan(page) -> str:
    """Rasterise a single PDF page and run OCR on it."""
    if settings.OCR_PDF_DPI < 72 or settings.OCR_PDF_DPI > 600:
        raise TextExtractionError(
            "OCR_PDF_DPI must be between 72 and 600."
        )
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - optional extra
        raise OCRUnavailableError(unavailable_message()) from exc

    pixmap = page.get_pixmap(
        dpi=settings.OCR_PDF_DPI, colorspace=pymupdf.csRGB, alpha=False
    )
    return ocr_image(pixmap.tobytes("png"))


def _extract_pdf_pages_pymupdf(data: bytes) -> tuple[list[str], int]:
    """Extract PDF text, falling back to OCR for pages without text."""
    try:
        import pymupdf
    except ImportError:  # optional extra not installed
        return _extract_pdf_pages_pypdf(data)

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise TextExtractionError("Could not read the PDF file.") from exc

    pages: list[str] = []
    ocr_pages = 0
    try:
        for page in document:
            text = _clean_text(page.get_text("text") or "")
            needs_ocr = len(text) < settings.OCR_MIN_TEXT_CHARS
            if needs_ocr and is_ocr_available():
                if ocr_pages >= settings.OCR_MAX_PAGES:
                    raise TextExtractionError(
                        f"This PDF needs OCR on more than {settings.OCR_MAX_PAGES} "
                        "pages. Split the document into smaller files and upload "
                        "them separately."
                    )
                ocr_text = _ocr_pdf_scan(page).strip()
                ocr_pages += 1
                if ocr_text:
                    text = f"{text}\n{ocr_text}".strip() if text else ocr_text
            pages.append(text)
        if ocr_pages:
            logger.info(
                "pdf_ocr_pages_processed",
                extra={"extra_fields": {"pages": ocr_pages}},
            )
        return pages, document.page_count
    finally:
        document.close()


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Return ``(text_with_page_breaks, page_count)``.

    Uses MuPDF when available (required for scanned-page OCR) and falls back
    to pypdf for text-only PDFs when the optional extra is not installed.
    """
    try:
        pages, page_count = _extract_pdf_pages_pymupdf(data)
    except OCRUnavailableError as exc:
        raise TextExtractionError(str(exc)) from exc
    except OCRProcessingError as exc:
        raise TextExtractionError(str(exc)) from exc

    text = "\f".join(pages)
    if not text.strip():
        raise TextExtractionError(
            "No text could be extracted from this PDF. It may be a scanned "
            "document and OCR is not available; upload a text-based PDF or "
            "install the OCR extra."
        )
    return text, page_count


def extract_image_text(data: bytes) -> tuple[str, int]:
    if not is_ocr_available():
        raise TextExtractionError(unavailable_message())
    try:
        text = ocr_image(data)
    except (OCRUnavailableError, OCRProcessingError) as exc:
        raise TextExtractionError(str(exc)) from exc
    if not text.strip():
        raise TextExtractionError(
            "No readable text was found in this image. Try a clearer scan "
            "with better lighting, or upload a text-based PDF."
        )
    logger.info("image_ocr_extracted", extra={"extra_fields": {"chars": len(text)}})
    return text, 1


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise TextExtractionError("Could not decode the text file.")


def extract_docx_text(data: bytes) -> tuple[str, int]:
    """Extract paragraphs and tables from a .docx document."""
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency is bundled
        raise TextExtractionError("Word (.docx) support is not installed.") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise TextExtractionError("Could not read the Word document.") from exc

    blocks: list[str] = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))

    text = "\n".join(blocks).strip()
    if not text:
        raise TextExtractionError(
            "No readable text was found in this Word document."
        )
    logger.info("docx_extracted", extra={"extra_fields": {"chars": len(text)}})
    return text, 1


def _rows_to_text(rows: list[list[object]]) -> str:
    lines: list[str] = []
    for row in rows:
        cells = ["" if cell is None else str(cell).strip() for cell in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _extract_xlsx_text(data: bytes) -> tuple[str, int]:
    import openpyxl

    workbook = openpyxl.load_workbook(
        io.BytesIO(data), read_only=True, data_only=True
    )
    try:
        pages: list[str] = []
        for sheet in workbook.worksheets:
            text = _rows_to_text([list(row) for row in sheet.iter_rows(values_only=True)])
            pages.append(text)
        return "\f".join(pages), max(len(pages), 1)
    finally:
        workbook.close()


def _extract_xls_text(data: bytes) -> tuple[str, int]:
    import xlrd

    workbook = xlrd.open_workbook(file_contents=data)
    pages: list[str] = []
    for sheet in workbook.sheets():
        rows = [
            [sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)
        ]
        pages.append(_rows_to_text(rows))
    return "\f".join(pages), max(len(pages), 1)


def extract_spreadsheet_text(data: bytes, content_type: str) -> tuple[str, int]:
    """Extract every sheet of a spreadsheet, one sheet per page."""
    try:
        if content_type == "application/vnd.ms-excel":
            text, page_count = _extract_xls_text(data)
        else:
            text, page_count = _extract_xlsx_text(data)
    except TextExtractionError:
        raise
    except Exception as exc:
        raise TextExtractionError("Could not read the spreadsheet.") from exc

    if not text.strip():
        raise TextExtractionError(
            "No readable text was found in this spreadsheet."
        )
    logger.info(
        "spreadsheet_extracted",
        extra={"extra_fields": {"sheets": page_count, "chars": len(text)}},
    )
    return text, page_count


def extract_csv_text(data: bytes) -> tuple[str, int]:
    raw = _decode_text(data)
    try:
        rows = list(csv.reader(io.StringIO(raw)))
    except csv.Error as exc:
        raise TextExtractionError("Could not read the CSV file.") from exc
    text = _rows_to_text(rows).strip()
    if not text:
        raise TextExtractionError("No readable text was found in this CSV file.")
    return text, 1


def extract_plain_text(data: bytes) -> tuple[str, int]:
    text = _decode_text(data).strip()
    if not text:
        raise TextExtractionError("This file is empty.")
    return text, 1


def extract_text(data: bytes, content_type: str) -> tuple[str, int | None]:
    if content_type == "application/pdf":
        return extract_pdf_text(data)
    if content_type in {"image/jpeg", "image/png"}:
        return extract_image_text(data)
    if (
        content_type
        == "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ):
        return extract_docx_text(data)
    if content_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        return extract_spreadsheet_text(data, content_type)
    if content_type == "text/csv":
        return extract_csv_text(data)
    if content_type in {"text/markdown", "text/plain"}:
        return extract_plain_text(data)
    raise TextExtractionError("Unsupported document type for text extraction.")
