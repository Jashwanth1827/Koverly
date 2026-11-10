"""Upload support and text extraction across non-PDF file formats.

Covers DOCX, XLSX, XLS, CSV, Markdown, and plain text uploads end to end:
content sniffing, the processing pipeline, and field extraction.
"""

from __future__ import annotations

import io
import zipfile

from tests.conftest import auth_headers, create_family, register

SAMPLE = """Health Insurance Policy
Policy Number: HLT-901234
Insurer: Format Health Insurance
Policy Holder: Format User
Sum Insured: 750000
Premium: 15000
Nominee: Rita Format
"""


def _setup(client, email="format_user@example.com"):
    user = register(client, email, "Format User")
    family = create_family(client, user["access_token"])
    return user, family


def _upload(client, token, family_id, data, name, content_type):
    return client.post(
        f"/api/v1/families/{family_id}/documents",
        files={"file": (name, data, content_type)},
        headers=auth_headers(token),
    )


def _docx_bytes(text: str) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "TPA"
    table.rows[0].cells[1].text = "MedAssist TPA"
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Policy"
    for row in [
        ["Policy Number", "HLT-901234"],
        ["Insurer", "Format Health Insurance"],
        ["Sum Insured", 750000],
        ["Premium", 15000],
    ]:
        sheet.append(row)
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def test_docx_upload_extracts_fields(client):
    user, family = _setup(client)
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        _docx_bytes(SAMPLE),
        "policy.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "processed", detail
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "HLT-901234"
    assert fields["insurer"]["value"] == "Format Health Insurance"
    assert fields["tpa"]["value"] == "MedAssist TPA"


def test_xlsx_upload_extracts_fields(client):
    user, family = _setup(client)
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        _xlsx_bytes(),
        "policy.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "HLT-901234"
    assert fields["insurer"]["value"] == "Format Health Insurance"
    assert fields["sum_insured"]["value"] == "750000"
    assert fields["premium"]["value"] == "15000"


def test_csv_upload_extracts_fields(client):
    user, family = _setup(client)
    csv_data = (
        b"Policy Number,HLT-901234\n"
        b"Insurer,Format Health Insurance\n"
        b"Sum Insured,750000\n"
        b"Premium,15000\n"
    )
    resp = _upload(
        client, user["access_token"], family["id"], csv_data, "policy.csv", "text/csv"
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "HLT-901234"
    assert fields["insurer"]["value"] == "Format Health Insurance"


def test_markdown_upload_extracts_fields(client):
    user, family = _setup(client)
    md = (
        b"# Health Insurance Policy\n\n"
        b"**Policy Number:** HLT-901234\n\n"
        b"**Insurer:** Format Health Insurance\n"
        b"**Premium:** 15000\n"
    )
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        md,
        "policy.md",
        "text/markdown",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "HLT-901234"


def test_txt_upload_extracts_fields(client):
    user, family = _setup(client)
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        SAMPLE.encode(),
        "policy.txt",
        "text/plain",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "HLT-901234"
    assert fields["nominee"]["value"] == "Rita Format"


def test_upload_rejects_binary_declared_as_text(client):
    user, family = _setup(client)
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        b"\x00\x01\x02\x03\xff\xfe binary",
        "not-text.txt",
        "text/plain",
    )
    assert resp.status_code == 422


def test_upload_rejects_unknown_type(client):
    user, family = _setup(client)
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        b"MZ\x90\x00 executable",
        "evil.exe",
        "application/octet-stream",
    )
    assert resp.status_code == 422


def test_plain_zip_claiming_xlsx_is_rejected(client):
    """A generic zip claiming to be a workbook must not enter the pipeline.

    Content sniffing inspects the OOXML parts, so a zip that is neither a Word
    document nor a real spreadsheet is rejected at upload with a clear message
    instead of failing processing later.
    """
    user, family = _setup(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")
    resp = _upload(
        client,
        user["access_token"],
        family["id"],
        buf.getvalue(),
        "fake.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 422
    assert "supported" in resp.json()["error"]["message"].lower()
