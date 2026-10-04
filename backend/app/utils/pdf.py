"""Minimal, dependency-free PDF writer for generated summaries.

Only the built-in Helvetica fonts are used, so this produces a valid PDF with
no third-party dependency. Text is escaped and wrapped; it is not a
general-purpose layout engine.
"""

from __future__ import annotations

from datetime import datetime, timezone

PAGE_WIDTH = 595  # A4 @ 72dpi
PAGE_HEIGHT = 842
MARGIN = 56
LINE_HEIGHT = 16
MAX_LINES_PER_PAGE = int((PAGE_HEIGHT - 2 * MARGIN) / LINE_HEIGHT)

# Font resource name -> PDF BaseFont.
_FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold"}
_FONT_SIZE = 11
_WRAP_CHARS = 84


_REPLACEMENTS = {
    "\u2014": "-", "\u2013": "-", "\u2022": "-", "\u00b7": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u00a0": " ", "\u20b9": "Rs.",
}


def _normalize(text: str) -> str:
    """Map common unicode punctuation to Latin-1-safe equivalents.

    The PDF uses built-in fonts with a Latin-1 encoding, so anything outside
    that range would otherwise be dropped to '?'.
    """
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape(text: str) -> str:
    text = _normalize(text)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, max_chars: int = _WRAP_CHARS) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _content_stream(lines: list[tuple[str, str, int]]) -> bytes:
    """``lines`` is a list of (font, text, indent_px)."""
    ops = ["BT"]
    y = PAGE_HEIGHT - MARGIN
    current_font = None
    for font, text, indent in lines:
        if font != current_font:
            ops.append(f"/{font} {_FONT_SIZE} Tf")
            current_font = font
        ops.append(f"1 0 0 1 {MARGIN + indent} {y} Tm")
        ops.append(f"({_escape(text)}) Tj")
        y -= LINE_HEIGHT
    ops.append("ET")
    return "\n".join(ops).encode("latin-1", "replace")


def _build_pdf(page_streams: list[bytes]) -> bytes:
    """Assemble a PDF with one page per content stream."""
    font_ids = {name: 3 + i for i, name in enumerate(_FONTS)}
    first_page_id = 3 + len(_FONTS)
    page_ids = [first_page_id + 2 * i for i in range(len(page_streams))]

    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    font_res = " ".join(f"/{name} {fid} 0 R" for name, fid in font_ids.items())
    resources = f"<< /Font << {font_res} >> >>".encode()
    for name, fid in font_ids.items():
        objects[fid] = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /"
            + _FONTS[name].encode()
            + b" >>"
        )

    for i, stream in enumerate(page_streams):
        page_id = page_ids[i]
        content_id = page_id + 1
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + f"{PAGE_WIDTH} {PAGE_HEIGHT}".encode()
            + b"] /Resources "
            + resources
            + b" /Contents "
            + f"{content_id} 0 R".encode()
            + b" >>"
        )
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    total = max(objects) + 1
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for idx in range(1, total):
        body = objects[idx]
        offsets[idx] = len(out)
        out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {total}\n".encode()
    out += b"0000000000 65535 f \n"
    for idx in range(1, total):
        out += f"{offsets[idx]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _paginate(lines: list[tuple[str, str, int]]) -> list[bytes]:
    pages = [
        _content_stream(lines[start : start + MAX_LINES_PER_PAGE])
        for start in range(0, len(lines), MAX_LINES_PER_PAGE)
    ]
    return pages or [_content_stream([])]


def build_policy_summary_pdf(
    *,
    family_name: str,
    policy: dict,
    documents: list[dict],
    generated_at: datetime | None = None,
) -> bytes:
    """Render a single-policy summary PDF from already-serialized values."""
    when = generated_at or datetime.now(timezone.utc)
    lines: list[tuple[str, str, int]] = [
        ("F2", f"{policy.get('insurer') or 'Policy'} — policy summary", 0),
        ("F1", f"Family: {family_name}", 0),
        ("F1", f"Generated: {when.strftime('%d %b %Y %H:%M UTC')}", 0),
        ("F1", "", 0),
    ]

    def section(heading: str) -> None:
        lines.append(("F2", heading, 0))

    def field(label: str, value: object) -> None:
        text = str(value) if value not in (None, "") else "—"
        for i, wrapped in enumerate(_wrap(f"{label}: {text}")):
            lines.append(("F1", wrapped, 0 if i == 0 else 12))

    section("Policy details")
    for label, key in (
        ("Type", "policy_type"),
        ("Insurer", "insurer"),
        ("Policy number", "policy_number"),
        ("Policyholder", "policyholder_name"),
        ("Status", "status"),
        ("Sum insured", "sum_insured"),
        ("Premium", "premium"),
        ("Premium frequency", "premium_frequency"),
        ("Start date", "start_date"),
        ("Expiry date", "expiry_date"),
        ("Renewal date", "renewal_date"),
        ("Maturity date", "maturity_date"),
        ("Nominee", "nominee"),
        ("Notes", "notes"),
    ):
        field(label, policy.get(key))

    metadata = policy.get("metadata_json") or {}
    if metadata:
        lines.append(("F1", "", 0))
        section("Additional details")
        for key, value in sorted(metadata.items()):
            field(str(key).replace("_", " ").capitalize(), value)

    lines.append(("F1", "", 0))
    section("Documents on file")
    if documents:
        for doc in documents:
            status = doc.get("document_type") or "policy"
            if doc.get("status"):
                status = f"{status} · {doc['status']}"
            field(doc.get("original_filename") or "document", status)
    else:
        field("Documents", "None linked")

    lines.append(("F1", "", 0))
    lines.append(
        (
            "F1",
            "This summary reflects the values recorded in Koverly. It is not an "
            "insurer's confirmation of cover. Always verify against the original "
            "policy document issued by your insurer.",
            0,
        )
    )
    return _build_pdf(_paginate(lines))
