"""Tests for image OCR and scanned-PDF text extraction.

These run only when the optional OCR extra is installed; the deterministic
behaviour without it (explicit failure, never fabricated text) is covered by
``test_documents.py`` and by the disabled-backend unit test below.
"""

from __future__ import annotations

import io

import pytest

from app.core.config import settings
from app.utils.ocr import is_ocr_available, ocr_backend_name
from app.utils.text_extract import TextExtractionError, extract_image_text
from tests.conftest import auth_headers, create_family, register

OCR_TEXT_LINES = [
    "Health Insurance Policy",
    "Policy Number HLT778899",
    "Sum Insured 500000",
]


def _require_ocr():
    pytest.importorskip("rapidocr_onnxruntime")
    pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")
    if not is_ocr_available():
        pytest.skip("OCR backend is disabled in this environment")


def _policy_image_bytes() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1000, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    for index, line in enumerate(OCR_TEXT_LINES):
        draw.text((40, 40 + index * 60), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_ocr_disabled_reports_reason_without_fabricating(monkeypatch):
    monkeypatch.setattr(settings, "OCR_BACKEND", "none")
    assert ocr_backend_name() == "none"
    assert is_ocr_available() is False
    with pytest.raises(TextExtractionError, match="disabled"):
        extract_image_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def test_image_upload_is_ocr_processed(client):
    _require_ocr()
    user = register(client, "ocr_image@example.com", "OCR Image")
    family = create_family(client, user["access_token"])
    png = _policy_image_bytes()

    resp = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("policy.png", png, "image/png")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["status"] in {"uploaded", "processing", "processed"}

    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "processed", detail
    assert detail["page_count"] == 1


def test_scanned_pdf_pages_are_ocr_processed(client):
    _require_ocr()
    import pymupdf

    user = register(client, "ocr_pdf@example.com", "OCR PDF")
    family = create_family(client, user["access_token"])

    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=_policy_image_bytes())
    pdf = document.tobytes()
    document.close()

    resp = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("scanned.pdf", pdf, "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()

    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "processed", detail
    assert detail["page_count"] == 1
