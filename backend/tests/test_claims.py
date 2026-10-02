"""Claim CRUD, status transition, and timeline tests."""

from __future__ import annotations

from tests.conftest import auth_headers, create_family, create_policy, register


def _setup(client):
    user = register(client, "claim_user@example.com", "Claim User")
    family = create_family(client, user["access_token"])
    policy = create_policy(client, user["access_token"], family["id"])
    return user, family, policy


def _create_claim(client, token, family_id, policy_id):
    resp = client.post(
        f"/api/v1/families/{family_id}/claims",
        json={
            "family_id": family_id,
            "policy_id": policy_id,
            "claim_type": "hospitalisation",
            "claim_amount": "45000",
            "provider": "City Hospital",
            "incident_date": "2025-01-10",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_claim_starts_draft_with_timeline(client):
    user, family, policy = _setup(client)
    claim = _create_claim(client, user["access_token"], family["id"], policy["id"])
    assert claim["status"] == "draft"

    detail = client.get(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert len(detail["events"]) == 1
    assert detail["events"][0]["status"] == "draft"


def test_valid_status_transition_records_event(client):
    user, family, policy = _setup(client)
    claim = _create_claim(client, user["access_token"], family["id"], policy["id"])

    resp = client.patch(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}",
        json={"status": "submitted"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"

    detail = client.get(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    statuses = [e["status"] for e in detail["events"]]
    assert statuses == ["draft", "submitted"]


def test_invalid_status_transition_rejected(client):
    user, family, policy = _setup(client)
    claim = _create_claim(client, user["access_token"], family["id"], policy["id"])
    # draft -> settled is not allowed.
    resp = client.patch(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}",
        json={"status": "settled"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_full_claim_lifecycle(client):
    user, family, policy = _setup(client)
    claim = _create_claim(client, user["access_token"], family["id"], policy["id"])
    for status in ["submitted", "under_review", "approved", "settled", "closed"]:
        resp = client.patch(
            f"/api/v1/families/{family['id']}/claims/{claim['id']}",
            json={"status": status},
            headers=auth_headers(user["access_token"]),
        )
        assert resp.status_code == 200, f"{status}: {resp.text}"
    detail = client.get(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert detail["status"] == "closed"
    assert len(detail["events"]) == 6


def test_claim_documents(client):
    user, family, policy = _setup(client)
    claim = _create_claim(client, user["access_token"], family["id"], policy["id"])
    from tests.conftest import make_pdf_bytes

    pdf = make_pdf_bytes("Discharge Summary\nPatient: Jane")
    resp = client.post(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}/documents",
        files={"file": ("discharge.pdf", pdf, "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201
    docs = client.get(
        f"/api/v1/families/{family['id']}/claims/{claim['id']}/documents",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert len(docs) == 1
    assert docs[0]["claim_id"] == claim["id"]


def test_claim_requires_valid_policy(client):
    user, family, policy = _setup(client)
    resp = client.post(
        f"/api/v1/families/{family['id']}/claims",
        json={
            "family_id": family["id"],
            "policy_id": "does-not-exist",
            "claim_type": "x",
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_list_claims_filter_by_status(client):
    user, family, policy = _setup(client)
    _create_claim(client, user["access_token"], family["id"], policy["id"])
    resp = client.get(
        f"/api/v1/families/{family['id']}/claims?status=draft",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.json()["total"] == 1
    resp2 = client.get(
        f"/api/v1/families/{family['id']}/claims?status=approved",
        headers=auth_headers(user["access_token"]),
    )
    assert resp2.json()["total"] == 0
