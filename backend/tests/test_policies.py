"""Policy CRUD, filtering, and aggregation tests."""

from __future__ import annotations

from tests.conftest import auth_headers, create_family, create_policy, register


def _setup(client):
    user = register(client, "policy_user@example.com", "Policy User")
    family = create_family(client, user["access_token"])
    return user, family


def test_create_and_get_policy(client):
    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    assert policy["insurer"] == "Acme Health"
    assert policy["policy_type"] == "health"

    resp = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["policy_number"] == "POL-0001"


def test_update_policy(client):
    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    resp = client.patch(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        json={"premium": "15000", "status": "lapsed"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "lapsed"
    assert float(body["premium"]) == 15000.0


def test_delete_policy(client):
    user, family = _setup(client)
    policy = create_policy(client, user["access_token"], family["id"])
    resp = client.delete(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    gone = client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert gone.status_code == 404


def test_list_and_filter_policies(client):
    user, family = _setup(client)
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="life", insurer="LifeCo", policy_number="L1",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="motor", insurer="MotorCo", policy_number="M1",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/policies?policy_type=life",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["policy_type"] == "life"


def test_search_policies(client):
    user, family = _setup(client)
    create_policy(client, user["access_token"], family["id"], insurer="UniqueInsurer")
    resp = client.get(
        f"/api/v1/families/{family['id']}/policies?search=uniqueinsurer",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.json()["total"] == 1


def test_policy_summary_annualizes_premium(client):
    user, family = _setup(client)
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="health", premium="1000", premium_frequency="monthly",
        sum_insured="500000",
    )
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="life", premium="12000", premium_frequency="yearly",
        sum_insured="5000000", policy_number="LIFE-1",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/policies/summary",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    # 1000*12 + 12000 = 24000
    assert float(body["total_annual_premium"]) == 24000.0
    assert float(body["total_life_coverage"]) == 5000000.0
    assert float(body["total_health_coverage"]) == 500000.0
    assert body["active_policies"] == 2


def test_policy_validates_member_belongs_to_family(client):
    user, family = _setup(client)
    resp = client.post(
        f"/api/v1/families/{family['id']}/policies",
        json={
            "family_id": family["id"],
            "policy_type": "life",
            "insurer": "X",
            "policy_number": "N",
            "member_id": "nonexistent-member",
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_policy_requires_authentication(client):
    user, family = _setup(client)
    resp = client.get(f"/api/v1/families/{family['id']}/policies")
    assert resp.status_code == 401
