"""Document vault, upload validation, and processing pipeline tests."""

from __future__ import annotations

from tests.conftest import (
    auth_headers,
    create_family,
    create_policy,
    make_pdf_bytes,
    register,
)

SAMPLE_POLICY_TEXT = """Health Insurance Policy
Policy Number: HLT-778899
Insurer: Acme Health Insurance
Policy Holder: Jane Doe
Sum Insured: 500000
Premium: 12500
Premium Frequency: Yearly
Start Date: 01/04/2024
Expiry Date: 31/03/2025
Nominee: John Doe
TPA: MedAssist TPA
Waiting Period: 24 months
Deductible: 5000
"""


def _setup(client):
    user = register(client, "doc_user@example.com", "Doc User")
    family = create_family(client, user["access_token"])
    return user, family


def _upload(client, token, family_id, text, name="policy.pdf", **params):
    pdf = make_pdf_bytes(text)
    return client.post(
        f"/api/v1/families/{family_id}/documents",
        files={"file": (name, pdf, "application/pdf")},
        headers=auth_headers(token),
        params=params,
    )


def test_upload_rejects_non_pdf_masquerade(client):
    user, family = _setup(client)
    # Declared as PDF but content is not a PDF.
    resp = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("fake.pdf", b"just some text", "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_upload_rejects_oversized_file(client):
    user, family = _setup(client)
    # MAX_UPLOAD_BYTES is 5MB in tests; send 6MB.
    big = b"%PDF-1.4\n" + b"0" * (6 * 1024 * 1024)
    resp = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("big.pdf", big, "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_upload_rejects_duplicate(client):
    user, family = _setup(client)
    first = _upload(client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT)
    assert first.status_code == 201
    second = _upload(client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT)
    assert second.status_code == 422


def test_upload_and_process_pipeline(client):
    user, family = _setup(client)
    resp = _upload(client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT)
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["status"] in {"uploaded", "processing", "processed"}

    # BackgroundTasks run synchronously in TestClient; fetch the final state.
    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "processed", detail
    assert detail["page_count"] == 1


def test_extraction_produces_fields_with_provenance(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    resp = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    fields = {f["field_name"]: f for f in resp.json()}

    assert fields["policy_number"]["found"] is True
    assert fields["policy_number"]["value"] == "HLT-778899"
    assert fields["policy_number"]["source_page"] == 1
    assert fields["insurer"]["value"].startswith("Acme Health")
    assert fields["nominee"]["value"] == "John Doe"
    assert fields["waiting_period"]["value"] == "24 months"

    # A field genuinely absent must be marked not found — never invented.
    assert fields["maturity_date"]["found"] is False
    assert fields["maturity_date"]["value"] is None


def test_confirm_extraction_applies_to_policy(client):
    user, family = _setup(client)
    policy = create_policy(
        client, user["access_token"], family["id"], policy_number="PLACEHOLDER"
    )
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT,
        policy_id=policy["id"],
    ).json()

    resp = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions/confirm",
        json={
            "policy_id": policy["id"],
            "confirm": {"policy_number": "HLT-778899", "nominee": "John Doe"},
            "reject": ["maturity_date"],
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200, resp.text

    updated = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert updated["policy_number"] == "HLT-778899"
    assert updated["nominee"] == "John Doe"


def test_confirm_extraction_applies_typed_fields(client):
    """Extracted money and dates must land in their real policy columns.

    Regression: these fields were previously written into metadata_json as raw
    strings, so confirming them left the policy's numeric/date columns empty.
    """
    user, family = _setup(client)
    policy = create_policy(
        client, user["access_token"], family["id"], policy_number="PLACEHOLDER"
    )
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT,
        policy_id=policy["id"],
    ).json()

    resp = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions/confirm",
        json={
            "policy_id": policy["id"],
            "confirm": {
                "insurer": "Acme Health Insurance",
                "sum_insured": "500000",
                "premium": "12500",
                "start_date": "01/04/2024",
                "expiry_date": "31/03/2025",
            },
            "reject": [],
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200, resp.text

    updated = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert updated["insurer"] == "Acme Health Insurance"
    assert float(updated["sum_insured"]) == 500000
    assert float(updated["premium"]) == 12500
    assert updated["start_date"] == "2024-04-01"
    assert updated["expiry_date"] == "2025-03-31"


def test_confirm_extraction_preserves_unparseable_values(client):
    """A value that cannot be coerced must not be silently dropped."""
    user, family = _setup(client)
    policy = create_policy(
        client, user["access_token"], family["id"], policy_number="PLACEHOLDER",
        sum_insured=None, premium=None,
    )
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT,
        policy_id=policy["id"],
    ).json()

    resp = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions/confirm",
        json={
            "policy_id": policy["id"],
            "confirm": {"sum_insured": "as per schedule", "expiry_date": "not a date"},
            "reject": [],
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200, resp.text

    updated = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert updated["sum_insured"] is None
    assert updated["expiry_date"] is None
    # The raw text is retained in metadata rather than discarded.
    assert updated["metadata_json"]["sum_insured"] == "as per schedule"
    assert updated["metadata_json"]["expiry_date"] == "not a date"


def test_confirm_requires_policy_link(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    resp = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions/confirm",
        json={"confirm": {"policy_number": "X"}, "reject": []},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_document_download_requires_auth(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    resp = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/download"
    )
    assert resp.status_code == 401


def test_document_delete_removes_file(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    resp = client.delete(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    assert client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}",
        headers=auth_headers(user["access_token"]),
    ).status_code == 404


def test_image_upload_fails_processing_with_clear_reason(client):
    """OCR is not configured, so images must fail explicitly — never fabricate."""
    user, family = _setup(client)
    # Minimal valid PNG header.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    resp = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("scan.png", png, "image/png")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]
    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc_id}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "failed"
    assert "OCR" in (detail["processing_error"] or "")


REALISTIC_POLICY_TEXT = """HDFC ERGO General Insurance Company Limited
Health Suraksha Insurance Policy

Policy No.: 2315001234567890
Policyholder Name: Ramesh Kumar Sharma
Date of Commencement: 01/04/2024
Policy Period: 01/04/2024 to 31/03/2025
Sum Insured: Rs. 5,00,000
Premium Amount: Rs. 12,450
Premium Frequency: Yearly
Nominee Name: Sunita Sharma
TPA: MediAssist Healthcare Services
Claim Helpline: 1800-266-8844
Waiting Period: 30 days
"""


# Mirrors the layout of a real HDFC ERGO health policy welcome letter (spaced
# policy number, salutation-style name, Section 80D premium certificate, period
# phrase). Values are synthetic.
HDFC_STYLE_POLICY_TEXT = """Mr A B Sample
-
-
HNO100 FLOT NOB27 GANDHI
NAGAR
BALAJI TOWERS
HYDERABAD
TELANGANA - 500080
Contact No.: 9000000000
Email: sample@example.com
Policy No : 1234 5678 9012 3456 000
Renewal of Your Optima Restore Floater Insurance Policy
Dear Mr A B Sample ,
Welcome to HDFC ERGO General Insurance Company Limited. We are pleased to issue you Renewal of Your Optima Restore Floater Insurance Policy.
Certificate for the purpose of deduction under Section 80 D of Income Tax Act, 1961*
This is to certify that the MR. A B SAMPLE has paid Rs. 23660 (Rupees Twenty-Three Thousand Six Hundred Sixty And Zero Paise Only) towards
premium for Optima Restore Floater Policy No. 1234567890123456000 issued to MR. A B SAMPLE for period of 05/01/2023 to 04/01/2024.
For and on behalf of HDFC ERGO General Insurance Company Limited
HDFC ERGO General Insurance Company Limited
1234567890123456000
HDFC ERGO General Insurance Company Limited.  IRDAI Reg No.146
"""


def test_extraction_handles_hdfc_style_letter(client):
    """Regression: spaced policy numbers, salutation names, 'has paid Rs. X'
    premium and 'for period of A to B' dates are all recoverable."""
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], HDFC_STYLE_POLICY_TEXT,
        name="hdfc_style.pdf",
    ).json()
    fields = {
        f["field_name"]: f["value"]
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
        if f["found"]
    }
    assert fields["policy_number"] == "1234 5678 9012 3456 000"
    assert fields["insurer"] == "HDFC ERGO General Insurance Company Limited"
    assert fields["policyholder_name"] == "A B Sample"
    assert fields["premium"] == "23660"
    assert fields["start_date"] == "05/01/2023"
    assert fields["expiry_date"] == "04/01/2024"
    # Not present anywhere in the text -> must not be invented.
    assert "sum_insured" not in fields
    assert "nominee" not in fields


def test_classifies_hdfc_style_letter_as_health():
    """The insurer type is inferred from the document text itself."""
    import asyncio

    from app.ai.null_provider import NullProvider

    assert asyncio.run(NullProvider().classify_document(HDFC_STYLE_POLICY_TEXT)) == "health"


def test_extraction_handles_realistic_document_labels(client):
    """Regression: insurer headings, 'Policy No.:' and period ranges were missed."""
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], REALISTIC_POLICY_TEXT,
        name="realistic.pdf",
    ).json()
    fields = {
        f["field_name"]: f
        for f in client.get(
            f"/api/v1/families/{family['id']}/documents/{doc['id']}/extractions",
            headers=auth_headers(user["access_token"]),
        ).json()
    }
    assert fields["policy_number"]["value"] == "2315001234567890"
    assert fields["insurer"]["value"].startswith("HDFC ERGO")
    assert fields["policyholder_name"]["value"] == "Ramesh Kumar Sharma"
    assert fields["sum_insured"]["value"] == "5,00,000"
    assert fields["premium"]["value"] == "12,450"
    assert fields["start_date"]["value"] == "01/04/2024"
    assert fields["expiry_date"]["value"] == "31/03/2025"
    assert fields["tpa"]["value"].startswith("MediAssist")


def test_signed_url_supports_attachment_disposition(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()

    inline = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/signed-url",
        headers=auth_headers(user["access_token"]),
    ).json()["url"]
    inline_resp = client.get(inline)
    assert inline_resp.status_code == 200
    assert inline_resp.headers["content-disposition"].startswith("inline")
    assert inline_resp.headers["content-type"].startswith("application/pdf")

    attach = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/signed-url"
        "?disposition=attachment",
        headers=auth_headers(user["access_token"]),
    ).json()["url"]
    attach_resp = client.get(attach)
    assert attach_resp.status_code == 200
    assert attach_resp.headers["content-disposition"].startswith("attachment")
    assert doc["original_filename"] in attach_resp.headers["content-disposition"]


def test_signed_url_tampering_is_rejected(client):
    """Changing the disposition or content type must invalidate the signature."""
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    url = client.post(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/signed-url",
        headers=auth_headers(user["access_token"]),
    ).json()["url"]

    tampered = url.replace("disposition=inline", "disposition=attachment")
    assert client.get(tampered).status_code == 403

    tampered_type = url + "&content_type=text/html"
    assert client.get(tampered_type).status_code == 403


def test_download_endpoint_sets_attachment_header(client):
    user, family = _setup(client)
    doc = _upload(
        client, user["access_token"], family["id"], SAMPLE_POLICY_TEXT
    ).json()
    resp = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/download",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")
    assert resp.content.startswith(b"%PDF-")


def test_policy_summary_pdf_is_generated(client):
    """The downloadable summary is generated by Koverly, never a raw upload."""
    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    resp = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}/summary.pdf",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["content-disposition"].startswith("attachment")
    body = resp.content
    assert body.startswith(b"%PDF-")
    assert b"%%EOF" in body
    assert b"Acme Health" in body


def test_policy_summary_pdf_requires_authorization(client):
    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    assert (
        client.get(f"/api/v1/families/{family['id']}/policies/{policy['id']}/summary.pdf").status_code
        == 401
    )


def test_policy_summary_pdf_hidden_from_other_family(client):
    from tests.conftest import auth_headers as _headers

    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    other = register(client, "doc_other@example.com", "Other")
    other_family = create_family(client, other["access_token"], "Other Family")
    resp = client.get(
        f"/api/v1/families/{other_family['id']}/policies/{policy['id']}/summary.pdf",
        headers=_headers(other["access_token"]),
    )
    assert resp.status_code == 404
