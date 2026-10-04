"""Shared pytest fixtures.

Environment is configured *before* importing the application so the cached
settings and engine bind to an isolated test database and storage directory.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

# --- Configure environment before any app import -------------------------- #
_TMP = Path(tempfile.mkdtemp(prefix="koverly-test-"))
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["STORAGE_LOCAL_ROOT"] = str(_TMP / "storage")
os.environ["STORAGE_BACKEND"] = "local"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["AI_PROVIDER"] = "null"
os.environ["NOTIFICATION_BACKEND"] = "noop"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["MAX_UPLOAD_BYTES"] = str(5 * 1024 * 1024)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import rate_limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _setup_database():
    """Fresh schema for every test — full isolation."""
    import asyncio

    import app.models  # noqa: F401

    async def _recreate():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_recreate())
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limiter.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def register(client: TestClient, email: str, name: str = "Test User") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": name, "password": "Passw0rd!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_family(client: TestClient, token: str, name: str = "Test Family") -> dict:
    resp = client.post(
        "/api/v1/families", json={"name": name}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_policy(
    client: TestClient, token: str, family_id: str, **overrides
) -> dict:
    payload = {
        "family_id": family_id,
        "policy_type": "health",
        "insurer": "Acme Health",
        "policy_number": "POL-0001",
        "sum_insured": "500000",
        "premium": "12000",
        "premium_frequency": "yearly",
    }
    payload.update(overrides)
    resp = client.post(
        f"/api/v1/families/{family_id}/policies",
        json=payload,
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_pdf_bytes(text: str) -> bytes:
    """Build a minimal, valid single-page PDF with extractable text.

    Constructed by hand so the test suite has no PDF-generation dependency.
    Each line of ``text`` becomes a text-showing operation.
    """
    lines = text.splitlines() or [""]
    ops = ["BT", "/F1 12 Tf", "72 720 Td"]
    for i, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if i:
            ops.append("0 -14 Td")
        ops.append(f"({escaped}) Tj")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1", "replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _render_text_image(lines: list[str]) -> bytes:
    """Render text into a PNG so OCR has real pixels to read."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1100, 120 + 70 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=44)
    except TypeError:  # pragma: no cover - very old Pillow
        font = ImageFont.load_default()
    for index, line in enumerate(lines):
        draw.text((30, 40 + 70 * index), line, font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def make_image_bytes(lines: list[str]) -> bytes:
    """A PNG containing rendered text, for image-OCR tests."""
    return _render_text_image(lines)


def make_scanned_pdf_bytes(lines: list[str]) -> bytes:
    """A PDF whose only page is an image of the text (no text layer).

    Simulates a scanned policy copy so the OCR path is exercised for real.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(_render_text_image(lines)))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PDF", resolution=200.0)
    return buffer.getvalue()


def ocr_available() -> bool:
    """Whether the test environment can actually run OCR."""
    from app.utils.text_extract import ocr_available as _available

    return _available()


def skip_without_ocr() -> None:
    if not ocr_available():
        pytest.skip("Tesseract OCR is not available in this environment")
