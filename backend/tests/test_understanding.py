"""Automatic document understanding: formats, classification, segmentation.

These tests cover the "upload anything, Koverly figures it out" requirement:
multi-format ingestion, document/insurance classification, multi-policy
segmentation, provenance, and user review — with no manual type selection.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ai.null_provider import NullProvider
from app.ai.taxonomy import DocumentClass, InsuranceCategory
from tests.conftest import (
    auth_headers,
    create_family,
    make_doc_bytes,
    make_docx_bytes,
    make_image_bytes,
    make_multipage_pdf_bytes,
    make_pdf_bytes,
    make_rtf_bytes,
    make_txt_bytes,
    register,
    skip_without_ocr,
)

HEALTH_POLICY = """HDFC ERGO General Insurance Company Limited
Policy Schedule - Optima Restore Floater
Policy No: HLT-778899
Policy Holder's Name: Mr John Doe
Total Sum Insured: Rs. 10,00,000
Premium: Rs. 12,500
Policy Period From 00:01 hrs on 01/04/2024 To 24:00 hrs on 31/03/2025
TPA: Medi Assist
Waiting Period: 24 months
Nominee: Jane Doe
"""

MOTOR_POLICY = """ICICI Lombard General Insurance Company Limited
Private Car Package Policy
Policy Number: MOT-445566
Registration Number: MH 12 AB 1234
IDV: Rs. 4,50,000
Premium: Rs. 9,800
Policy Period From 01/06/2024 To 31/05/2025
"""

LIFE_POLICY = """LIC of India
Jeevan Anand Endowment Plan
Policy No: LIF-112233
Sum Assured: Rs. 25,00,000
Premium: Rs. 18,000
Date of Commencement: 15/03/2020
Maturity Date: 15/03/2040
Nominee: Sunita Sharma
"""

NON_INSURANCE_TEXT = """Acme Corporation
Tax Invoice
Invoice Number: INV-2024-0099
Purchase Order: PO-7788
Item: Office chair, Quantity 4, Unit price Rs. 5,000
Total amount payable: Rs. 20,000
"""


def _setup(client, email="understand@example.com"):
    user = register(client, email, "Understand User")
    family = create_family(client, user["access_token"])
    return user, family


def _upload(client, token, family_id, filename, data, content_type):
    return client.post(
        f"/api/v1/families/{family_id}/documents",
        files={"file": (filename, data, content_type)},
        headers=auth_headers(token),
    )


# --------------------------------------------------------------------------- #
# Multi-format ingestion
# --------------------------------------------------------------------------- #
def test_uploads_pdf_and_analyses_it(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()

    detail = client.get(
        f"/api/v1/families/{family['id']}/documents/{doc['id']}/analysis",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["analysis"]["is_insurance"] is True
    assert detail["analysis"]["source_kind"] == "text_document"
    assert detail["candidate_count"] == 1
    candidate = detail["candidates"][0]
    assert candidate["category"] == "health"
    assert candidate["policy_type"] == "family_floater"


def test_uploads_docx_and_extracts(client):
    """A Word document is read without the user selecting a format."""
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.docx", make_docx_bytes(HEALTH_POLICY.splitlines()),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    fields = _fields(client, user, family, doc["id"])
    assert fields["policy_number"]["value"] == "HLT-778899"
    assert fields["insurer"]["value"].startswith("HDFC ERGO")


def test_uploads_txt_and_extracts(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.txt", make_txt_bytes(MOTOR_POLICY), "text/plain",
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    detail = _analysis(client, user, family, doc["id"])
    assert detail["candidates"][0]["category"] == "motor"


def test_uploads_rtf_and_extracts(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.rtf", make_rtf_bytes(LIFE_POLICY), "application/rtf",
    )
    assert resp.status_code == 201, resp.text
    fields = _fields(client, user, family, resp.json()["id"])
    assert fields["policy_number"]["value"] == "LIF-112233"


def test_uploads_legacy_doc_recovers_text(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.doc", make_doc_bytes(LIFE_POLICY), "application/msword",
    )
    assert resp.status_code == 201, resp.text
    fields = _fields(client, user, family, resp.json()["id"])
    assert fields["policy_number"]["value"] == "LIF-112233"


def test_uploads_image_and_ocrs_it(client):
    skip_without_ocr()
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "photo.png", make_image_bytes(["Policy No: IMG-909090", "Insurer: Acme Life"]),
        "image/png",
    )
    assert resp.status_code == 201, resp.text
    detail = _analysis(client, user, family, resp.json()["id"])
    assert detail["analysis"]["source_kind"] == "image_document"
    assert detail["analysis"]["ocr_used"] is True


def test_uploads_webp_image(client):
    skip_without_ocr()
    from PIL import Image

    import io as _io

    image = Image.open(_io.BytesIO(make_image_bytes(["Policy No: WEB-123456"])))
    buffer = _io.BytesIO()
    image.save(buffer, "WEBP")
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.webp", buffer.getvalue(), "image/webp",
    )
    assert resp.status_code == 201, resp.text


def test_rejects_unsupported_binary(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "archive.zip", b"PK\x03\x04" + bytes(range(200)), "application/zip",
    )
    assert resp.status_code == 422
    assert "supported" in resp.json()["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        (HEALTH_POLICY, InsuranceCategory.HEALTH.value),
        (MOTOR_POLICY, InsuranceCategory.MOTOR.value),
        (LIFE_POLICY, InsuranceCategory.LIFE.value),
    ],
)
def test_category_inferred_from_document(text, expected):
    provider = NullProvider()
    category, confidence = provider.classify_category(text)
    assert category == expected
    assert 0 < confidence <= 1


def test_document_class_detects_non_insurance():
    provider = NullProvider()
    document_class, _ = provider.classify_document_class(NON_INSURANCE_TEXT)
    assert document_class == DocumentClass.NON_INSURANCE_DOCUMENT.value


def test_non_insurance_document_creates_no_policy(client):
    """A non-insurance upload must not become a fake policy."""
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "invoice.txt", make_txt_bytes(NON_INSURANCE_TEXT), "text/plain",
    )
    assert resp.status_code == 201, resp.text
    detail = _analysis(client, user, family, resp.json()["id"])
    assert detail["analysis"]["is_insurance"] is False
    assert detail["candidate_count"] == 0
    assert detail["analysis"]["message"]

    listing = client.get(
        f"/api/v1/families/{family['id']}/policies",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert listing["total"] == 0


def test_motor_policy_type_and_subtype(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "car.pdf", make_pdf_bytes(MOTOR_POLICY + "\nComprehensive cover included\n"),
        "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    candidate = detail["candidates"][0]
    assert candidate["category"] == "motor"
    assert candidate["policy_type"] == "car"
    assert candidate["policy_subtype"] == "comprehensive"


# --------------------------------------------------------------------------- #
# Provenance & honesty
# --------------------------------------------------------------------------- #
def test_every_field_carries_provenance_and_evidence(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    fields = {f["field_name"]: f for f in detail["candidates"][0]["fields"]}

    number = fields["policy_number"]
    assert number["evidence"] == "explicitly_found"
    assert number["source_page"] == 1
    assert number["source_text"]
    assert number["review_status"] == "ai_extracted"

    # A field genuinely absent is recorded as not found, with no value.
    maturity = fields["maturity_date"]
    assert maturity["evidence"] == "not_found"
    assert maturity["value"] is None


def test_extraction_never_invents_absent_values(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    fields = _fields(client, user, family, resp.json()["id"])
    # The document has no maturity date; nothing must be fabricated.
    assert fields["maturity_date"]["value"] is None
    assert fields["maturity_date"]["evidence"] == "not_found"


# --------------------------------------------------------------------------- #
# Multi-policy documents
# --------------------------------------------------------------------------- #
def test_multiple_policies_in_one_document(client):
    """One upload may hold several policies; each becomes its own candidate."""
    bundle_pages = [
        HEALTH_POLICY,
        "Policy Schedule\nPolicy No: MOT-445566\n"
        "ICICI Lombard Private Car Package Policy\n"
        "Registration Number: MH 12 AB 1234\nIDV: Rs. 4,50,000\n"
        "Premium: Rs. 9,800\n",
        "Policy Schedule\nPolicy No: LIF-112233\n"
        "LIC of India Jeevan Anand Endowment Plan\n"
        "Sum Assured: Rs. 25,00,000\nPremium: Rs. 18,000\n"
        "Maturity Date: 15/03/2040\n",
    ]
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "bundle.pdf", make_multipage_pdf_bytes(bundle_pages), "application/pdf",
    )
    assert resp.status_code == 201, resp.text
    detail = _analysis(client, user, family, resp.json()["id"])
    assert detail["candidate_count"] >= 2
    categories = {c["category"] for c in detail["candidates"]}
    assert "motor" in categories


def test_segmentation_keeps_page_ranges():
    provider = NullProvider()
    bundle = (
        "Policy Schedule\nPolicy No: AAA-1\nHealth insurance mediclaim TPA\n"
        "\fPolicy Schedule\nPolicy No: BBB-2\nPrivate car package policy IDV\n"
    )
    candidates = asyncio.run(provider.extract_candidates(bundle, page_count=2))
    assert len(candidates) == 2
    assert candidates[0].page_start == 1
    assert candidates[1].page_start == 2


def test_segmented_fields_cite_real_page():
    """A field from the second policy must cite page 2, not segment page 1."""
    provider = NullProvider()
    bundle = (
        "Policy Schedule\nPolicy No: AAA-1\nHealth insurance mediclaim TPA\n"
        "\fPolicy Schedule\nPolicy No: BBB-2\nPrivate car package policy IDV\n"
    )
    candidates = asyncio.run(provider.extract_candidates(bundle, page_count=2))
    second = {f.field_name: f for f in candidates[1].fields}
    assert second["policy_number"].value == "BBB-2"
    assert second["policy_number"].source_page == 2


# --------------------------------------------------------------------------- #
# Review: confirm / correct
# --------------------------------------------------------------------------- #
def test_confirm_candidate_creates_policy(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    candidate = detail["candidates"][0]

    confirm = client.post(
        f"/api/v1/families/{family['id']}/documents/{resp.json()['id']}"
        f"/candidates/{candidate['id']}/confirm",
        json={"confirm": {"insurer": "HDFC ERGO", "policy_number": "HLT-778899"}},
        headers=auth_headers(user["access_token"]),
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["status"] == "confirmed"
    assert body["policy_id"]

    listing = client.get(
        f"/api/v1/families/{family['id']}/policies",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert listing["total"] == 1
    policy = listing["items"][0]
    assert policy["policy_type"] == "health"
    assert policy["policy_number"] == "HLT-778899"


def test_user_correction_is_recorded(client):
    """An edited value is applied and marked as user-edited, not AI-extracted."""
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    candidate = detail["candidates"][0]

    confirm = client.post(
        f"/api/v1/families/{family['id']}/documents/{resp.json()['id']}"
        f"/candidates/{candidate['id']}/confirm",
        json={
            "confirm": {
                "insurer": "HDFC ERGO General Insurance",
                "policy_number": "HLT-778899",
                "nominee": "Corrected Name",
            }
        },
        headers=auth_headers(user["access_token"]),
    ).json()
    fields = {f["field_name"]: f for f in confirm["fields"]}
    assert fields["nominee"]["value"] == "Corrected Name"
    assert fields["nominee"]["review_status"] == "user_edited"
    assert fields["nominee"]["confidence"] == 1.0


def test_confirm_candidate_requires_insurer_and_number(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    candidate = detail["candidates"][0]
    confirm = client.post(
        f"/api/v1/families/{family['id']}/documents/{resp.json()['id']}"
        f"/candidates/{candidate['id']}/confirm",
        json={"confirm": {"policy_number": "HLT-778899"}, "reject": ["insurer"]},
        headers=auth_headers(user["access_token"]),
    )
    assert confirm.status_code == 422


def test_reject_candidate_leaves_no_policy(client):
    user, family = _setup(client)
    resp = _upload(
        client, user["access_token"], family["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user, family, resp.json()["id"])
    candidate = detail["candidates"][0]
    rejected = client.post(
        f"/api/v1/families/{family['id']}/documents/{resp.json()['id']}"
        f"/candidates/{candidate['id']}/reject",
        headers=auth_headers(user["access_token"]),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    listing = client.get(
        f"/api/v1/families/{family['id']}/policies",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert listing["total"] == 0


# --------------------------------------------------------------------------- #
# Security: analysis is family-scoped
# --------------------------------------------------------------------------- #
def test_analysis_is_family_scoped(client):
    user_a = register(client, "a_analysis@example.com", "A")
    family_a = create_family(client, user_a["access_token"], "A Family")
    resp = _upload(
        client, user_a["access_token"], family_a["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    doc_id = resp.json()["id"]

    user_b = register(client, "b_analysis@example.com", "B")
    family_b = create_family(client, user_b["access_token"], "B Family")
    blocked = client.get(
        f"/api/v1/families/{family_b['id']}/documents/{doc_id}/analysis",
        headers=auth_headers(user_b["access_token"]),
    )
    assert blocked.status_code == 404


def test_candidate_confirm_is_family_scoped(client):
    user_a = register(client, "a_cand@example.com", "A")
    family_a = create_family(client, user_a["access_token"], "A Family")
    resp = _upload(
        client, user_a["access_token"], family_a["id"],
        "policy.pdf", make_pdf_bytes(HEALTH_POLICY), "application/pdf",
    )
    detail = _analysis(client, user_a, family_a, resp.json()["id"])
    candidate_id = detail["candidates"][0]["id"]

    user_b = register(client, "b_cand@example.com", "B")
    family_b = create_family(client, user_b["access_token"], "B Family")
    blocked = client.post(
        f"/api/v1/families/{family_b['id']}/documents/{resp.json()['id']}"
        f"/candidates/{candidate_id}/confirm",
        json={"confirm": {"insurer": "X", "policy_number": "Y"}},
        headers=auth_headers(user_b["access_token"]),
    )
    assert blocked.status_code == 404


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _analysis(client, user, family, document_id):
    resp = client.get(
        f"/api/v1/families/{family['id']}/documents/{document_id}/analysis",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fields(client, user, family, document_id):
    detail = _analysis(client, user, family, document_id)
    assert detail["candidate_count"] >= 1, detail
    return {f["field_name"]: f for f in detail["candidates"][0]["fields"]}
