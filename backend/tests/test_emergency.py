"""Emergency mode and subscription tests."""

from __future__ import annotations

from tests.conftest import auth_headers, create_family, create_policy, register


def _setup(client, email="emerg_user@example.com"):
    user = register(client, email, "Emerg User")
    family = create_family(client, user["access_token"])
    return user, family


def test_emergency_profile_lists_health_policies(client):
    user, family = _setup(client)
    policy = create_policy(
        client, user["access_token"], family["id"],
        policy_type="health", sum_insured="500000",
    )
    client.patch(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        json={"metadata_json": {"tpa": "MedAssist", "claim_contact": "1800123456"}},
        headers=auth_headers(user["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/emergency",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["policies"]) == 1
    assert body["policies"][0]["tpa"] == "MedAssist"
    assert body["claim_instructions"]
    contacts = {c["label"]: c["value"] for c in body["contacts"]}
    assert contacts.get("Acme Health TPA") == "MedAssist"


def test_emergency_excludes_non_relevant_policy_types(client):
    user, family = _setup(client, "emerg_excl@example.com")
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="motor", policy_number="CAR-1",
    )
    resp = client.get(
        f"/api/v1/families/{family['id']}/emergency",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.json()["policies"] == []


def test_emergency_share_is_scoped_and_expiring(client):
    user, family = _setup(client, "emerg_share@example.com")
    create_policy(client, user["access_token"], family["id"], policy_type="health")
    # A second, unrelated policy that must not appear.
    create_policy(
        client, user["access_token"], family["id"],
        policy_type="motor", policy_number="CAR-2",
    )

    share = client.post(
        f"/api/v1/families/{family['id']}/emergency/shares",
        json={"ttl_minutes": 60, "max_views": 2},
        headers=auth_headers(user["access_token"]),
    )
    assert share.status_code == 201
    token = share.json()["token"]

    # Public access (no auth header) returns only the emergency summary.
    public = client.get(f"/api/v1/emergency/share/{token}")
    assert public.status_code == 200
    body = public.json()
    assert "policies" in body
    assert "documents" not in body  # full vault is not exposed
    assert all(p["policy_type"] != "motor" for p in body["policies"])

    # Second view allowed, third blocked by max_views.
    assert client.get(f"/api/v1/emergency/share/{token}").status_code == 200
    assert client.get(f"/api/v1/emergency/share/{token}").status_code == 404


def test_emergency_share_revocation(client):
    user, family = _setup(client, "emerg_revoke@example.com")
    create_policy(client, user["access_token"], family["id"], policy_type="health")
    share = client.post(
        f"/api/v1/families/{family['id']}/emergency/shares",
        json={"ttl_minutes": 60},
        headers=auth_headers(user["access_token"]),
    ).json()
    revoke = client.delete(
        f"/api/v1/families/{family['id']}/emergency/shares/{share['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert revoke.status_code == 200
    assert client.get(f"/api/v1/emergency/share/{share['token']}").status_code == 404


def test_unknown_share_token_returns_404(client):
    assert client.get("/api/v1/emergency/share/nonexistent").status_code == 404


def test_subscription_defaults_to_free(client):
    user, family = _setup(client, "sub_user@example.com")
    resp = client.get(
        f"/api/v1/families/{family['id']}/subscription",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"


def test_subscription_plan_change_is_admin_only(client):
    owner = register(client, "sub_owner@example.com", "Sub Owner")
    viewer = register(client, "sub_viewer@example.com", "Sub Viewer")
    family = create_family(client, owner["access_token"])
    client.post(
        f"/api/v1/families/{family['id']}/invites",
        json={"email": "sub_viewer@example.com", "role": "viewer"},
        headers=auth_headers(owner["access_token"]),
    )
    denied = client.patch(
        f"/api/v1/families/{family['id']}/subscription",
        json={"plan": "pro"},
        headers=auth_headers(viewer["access_token"]),
    )
    assert denied.status_code == 403

    ok = client.patch(
        f"/api/v1/families/{family['id']}/subscription",
        json={"plan": "pro"},
        headers=auth_headers(owner["access_token"]),
    )
    assert ok.status_code == 200
    assert ok.json()["plan"] == "pro"
