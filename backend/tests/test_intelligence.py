"""Insurance intelligence, coverage map, dashboard, search, and audit tests."""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import auth_headers, create_family, create_policy, register


def _setup(client, email="intel_user@example.com"):
    user = register(client, email, "Intel User")
    family = create_family(client, user["access_token"])
    return user, family


def test_intelligence_flags_missing_nominee(client):
    user, family = _setup(client)
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="life", insurer="LifeCo", policy_number="L-1", nominee=None,
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/insurance-intelligence",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    kinds = {(i["kind"], i["title"]) for i in resp.json()["items"]}
    assert any(k == "missing_info" and "nominee" in t.lower() for k, t in kinds)


def test_intelligence_flags_expiring_policy(client):
    user, family = _setup(client)
    soon = (date.today() + timedelta(days=18)).isoformat()
    policy = create_policy(client, user["access_token"], family["id"])
    client.patch(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        json={"expiry_date": soon},
        headers=auth_headers(user["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/insurance-intelligence",
        headers=auth_headers(user["access_token"]),
    )
    items = resp.json()["items"]
    expiring = [i for i in items if i["kind"] == "expiring"]
    assert expiring
    assert "18 day" in expiring[0]["detail"]


def test_intelligence_overlap_is_phrased_cautiously(client):
    user, family = _setup(client)
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="personal_accident", policy_number="PA-1",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="personal_accident", policy_number="PA-2",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="personal_accident", policy_number="PA-3",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/insurance-intelligence",
        headers=auth_headers(user["access_token"]),
    )
    items = resp.json()["items"]
    overlaps = [i for i in items if i["kind"] == "potential_overlap"]
    assert overlaps
    assert "potential" in overlaps[0]["title"].lower()
    # Must not contain advisory language.
    assert "wasting" not in overlaps[0]["detail"].lower()


def test_coverage_map_is_data_driven(client):
    user, family = _setup(client)
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="life", sum_insured="1000000", policy_number="L-9",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="health", sum_insured="500000", policy_number="H-9",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/coverage-map",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    categories = {c["category"]: c for c in resp.json()["categories"]}
    assert categories["life"]["policy_count"] == 1
    assert float(categories["life"]["total_coverage"]) == 1000000.0
    assert categories["health"]["policy_count"] == 1


def test_dashboard_reflects_real_data(client):
    user, family = _setup(client, "dash_user@example.com")
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="health", premium="12000", premium_frequency="yearly",
        sum_insured="500000",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="life", premium="8000", premium_frequency="yearly",
        sum_insured="5000000", policy_number="LIFE-2",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/dashboard",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_policies"] == 2
    assert float(body["total_annual_premium"]) == 20000.0
    assert float(body["total_life_coverage"]) == 5000000.0
    assert float(body["total_health_coverage"]) == 500000.0


def test_search_finds_policy_and_member(client):
    user, family = _setup(client, "search_user@example.com")
    create_policy(
        client, user["access_token"], family["id"], insurer="FindableInsure"
    )
    client.post(
        f"/api/v1/families/{family['id']}/members",
        json={"name": "Findable Name", "relationship": "father"},
        headers=auth_headers(user["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/search?q=findable",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    kinds = {r["kind"] for r in resp.json()["results"]}
    assert "policy" in kinds
    assert "family_member" in kinds


def test_audit_log_records_sensitive_actions(client):
    user, family = _setup(client, "audit_user@example.com")
    policy = create_policy(client, user["access_token"], family["id"])
    client.patch(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        json={"premium": "999"},
        headers=auth_headers(user["access_token"]),
    )
    client.delete(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/audit-logs",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    actions = {a["action"] for a in resp.json()["items"]}
    assert {"policy_created", "policy_updated", "policy_deleted"} <= actions


def test_audit_metadata_sanitized(client):
    user, family = _setup(client, "audit_sanitize@example.com")
    from tests.conftest import make_pdf_bytes

    pdf = make_pdf_bytes("Policy Number: ABC\nInsurer: Acme")
    client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("p.pdf", pdf, "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    logs = client.get(
        f"/api/v1/families/{family['id']}/audit-logs",
        headers=auth_headers(user["access_token"]),
    ).json()["items"]
    upload = next(a for a in logs if a["action"] == "document_uploaded")
    # Raw document content must never be stored in audit metadata.
    assert "content" not in upload["metadata_json"]
    assert "extracted_text" not in upload["metadata_json"]
