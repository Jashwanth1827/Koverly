"""Family and family member tests."""

from __future__ import annotations

from tests.conftest import (
    auth_headers,
    create_family,
    create_policy,
    make_pdf_bytes,
    register,
)

from app.integrations.storage import get_storage


def test_create_family_adds_owner_member(client):
    user = register(client, "fam_owner@example.com", "Owner")
    family = create_family(client, user["access_token"], "The Owners")
    members = client.get(
        f"/api/v1/families/{family['id']}/members",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert len(members) == 1
    assert members[0]["role"] == "owner"
    assert members[0]["relationship"] == "self"


def test_add_and_update_member(client):
    user = register(client, "fam_adder@example.com", "Adder")
    family = create_family(client, user["access_token"])
    resp = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={"name": "Mother", "relationship": "mother", "blood_group": "O+"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201
    member = resp.json()
    assert member["relationship"] == "mother"

    upd = client.patch(
        f"/api/v1/families/{family['id']}/members/{member['id']}",
        json={"phone": "9999999999"},
        headers=auth_headers(user["access_token"]),
    )
    assert upd.status_code == 200
    assert upd.json()["phone"] == "9999999999"


def test_remove_member(client):
    user = register(client, "fam_remover@example.com", "Remover")
    family = create_family(client, user["access_token"])
    member = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={"name": "Brother", "relationship": "brother"},
        headers=auth_headers(user["access_token"]),
    ).json()
    resp = client.delete(
        f"/api/v1/families/{family['id']}/members/{member['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 200
    listing = client.get(
        f"/api/v1/families/{family['id']}/members",
        headers=auth_headers(user["access_token"]),
    ).json()
    assert all(m["id"] != member["id"] for m in listing)


def test_cannot_remove_owner(client):
    user = register(client, "fam_keepowner@example.com", "KeepOwner")
    family = create_family(client, user["access_token"])
    members = client.get(
        f"/api/v1/families/{family['id']}/members",
        headers=auth_headers(user["access_token"]),
    ).json()
    owner_member = members[0]
    resp = client.delete(
        f"/api/v1/families/{family['id']}/members/{owner_member['id']}",
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422


def test_invite_links_existing_account(client):
    owner = register(client, "invite_owner@example.com", "Invite Owner")
    other = register(client, "invitee@example.com", "Invitee")
    family = create_family(client, owner["access_token"])

    resp = client.post(
        f"/api/v1/families/{family['id']}/invites",
        json={"email": "invitee@example.com", "role": "member"},
        headers=auth_headers(owner["access_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == other["user"]["id"]

    # The invitee can now access the family.
    access = client.get(
        f"/api/v1/families/{family['id']}",
        headers=auth_headers(other["access_token"]),
    )
    assert access.status_code == 200
    assert access.json()["role"] == "member"


def test_invite_unknown_email_returns_404(client):
    owner = register(client, "invite_owner2@example.com", "Owner2")
    family = create_family(client, owner["access_token"])
    resp = client.post(
        f"/api/v1/families/{family['id']}/invites",
        json={"email": "ghost@example.com", "role": "member"},
        headers=auth_headers(owner["access_token"]),
    )
    assert resp.status_code == 404


def test_role_change(client):
    owner = register(client, "role_owner@example.com", "Role Owner")
    member = register(client, "role_member@example.com", "Role Member")
    family = create_family(client, owner["access_token"])
    invited = client.post(
        f"/api/v1/families/{family['id']}/invites",
        json={"email": "role_member@example.com", "role": "viewer"},
        headers=auth_headers(owner["access_token"]),
    ).json()

    resp = client.patch(
        f"/api/v1/families/{family['id']}/members/{invited['id']}/role",
        json={"role": "admin"},
        headers=auth_headers(owner["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_member_can_list_own_families(client):
    user = register(client, "multi_fam@example.com", "Multi")
    create_family(client, user["access_token"], "Family One")
    create_family(client, user["access_token"], "Family Two")
    resp = client.get("/api/v1/families", headers=auth_headers(user["access_token"]))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_delete_family_removes_all_related_data(client):
    """Deleting a family must cascade to policies, documents, claims, and
    members, and must purge stored files."""
    user = register(client, "fam_delete@example.com", "Deleter")
    family = create_family(client, user["access_token"], "Doomed Family")
    policy = create_policy(client, user["access_token"], family["id"])

    up = client.post(
        f"/api/v1/families/{family['id']}/documents",
        files={"file": ("d.pdf", make_pdf_bytes("Policy Number: DEL-1"), "application/pdf")},
        headers=auth_headers(user["access_token"]),
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    claim = client.post(
        f"/api/v1/families/{family['id']}/claims",
        json={
            "policy_id": policy["id"],
            "family_id": family["id"],
            "claim_type": "health",
            "claim_amount": "1000",
        },
        headers=auth_headers(user["access_token"]),
    )
    assert claim.status_code == 201, claim.text

    resp = client.delete(
        f"/api/v1/families/{family['id']}", headers=auth_headers(user["access_token"])
    )
    assert resp.status_code == 200, resp.text

    # Family and every child resource are gone.
    assert client.get(
        f"/api/v1/families/{family['id']}", headers=auth_headers(user["access_token"])
    ).status_code == 404
    assert client.get(
        f"/api/v1/families/{family['id']}/policies/{policy['id']}",
        headers=auth_headers(user["access_token"]),
    ).status_code == 404
    assert client.get(
        f"/api/v1/families/{family['id']}/documents/{doc_id}",
        headers=auth_headers(user["access_token"]),
    ).status_code == 404
    assert client.get("/api/v1/families", headers=auth_headers(user["access_token"])).json() == []

    # Stored file is purged from private storage.
    storage = get_storage()
    import asyncio

    assert asyncio.run(_storage_exists(storage, f"{family['id']}/{doc_id}.pdf")) is False


def test_non_owner_cannot_delete_family(client):
    owner = register(client, "fam_owner2@example.com", "Owner Two")
    other = register(client, "fam_other@example.com", "Other")
    family = create_family(client, owner["access_token"], "Protected Family")

    # An admin who is not the owner still cannot delete the family.
    client.post(
        f"/api/v1/families/{family['id']}/invites",
        json={"email": "fam_other@example.com", "role": "admin"},
        headers=auth_headers(owner["access_token"]),
    )
    resp = client.delete(
        f"/api/v1/families/{family['id']}", headers=auth_headers(other["access_token"])
    )
    assert resp.status_code in (403, 422)

    # A stranger sees 404 (family existence is not disclosed).
    stranger = register(client, "fam_stranger@example.com", "Stranger")
    resp2 = client.delete(
        f"/api/v1/families/{family['id']}", headers=auth_headers(stranger["access_token"])
    )
    assert resp2.status_code == 404


def test_family_delete_is_audited(client):
    """The destructive action is recorded, and the entry survives the delete."""
    import asyncio

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.claim import AuditLog

    user = register(client, "fam_audit_del@example.com", "Audit Deleter")
    family = create_family(client, user["access_token"], "Audited Family")
    family_id = family["id"]

    resp = client.delete(
        f"/api/v1/families/{family_id}", headers=auth_headers(user["access_token"])
    )
    assert resp.status_code == 200

    async def _fetch():
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(AuditLog).where(AuditLog.resource_id == family_id)
                )
            ).scalars().all()
            return [(r.action, r.family_id) for r in rows]

    actions = asyncio.run(_fetch())
    assert ("family_deleted", None) in actions


async def _storage_exists(storage, key: str) -> bool:
    try:
        await storage.get(key)
        return True
    except Exception:  # noqa: BLE001
        return False


def test_add_member_accepts_blank_optional_fields(client):
    """Blank HTML inputs must be treated as absent, not as invalid values."""
    user = register(client, "fam_blank@example.com", "Blank")
    family = create_family(client, user["access_token"])
    resp = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={
            "name": "  Mother  ",
            "relationship": "mother",
            "date_of_birth": "",
            "email": "",
            "phone": "",
            "blood_group": "",
        },
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Mother"
    assert body["date_of_birth"] is None
    assert body["email"] is None


def test_add_member_validation_message_names_field(client):
    """A rejected payload must say which field failed, not just 'Invalid request.'"""
    user = register(client, "fam_msg@example.com", "Msg")
    family = create_family(client, user["access_token"])
    resp = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={"name": "X", "relationship": "father", "blood_group": "not-a-blood-group"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422
    message = resp.json()["error"]["message"]
    assert message != "Invalid request."
    assert "Blood group" in message


def test_add_member_rejects_bad_email_with_clear_message(client):
    user = register(client, "fam_email@example.com", "Email")
    family = create_family(client, user["access_token"])
    resp = client.post(
        f"/api/v1/families/{family['id']}/members",
        json={"name": "X", "relationship": "father", "email": "not-an-email"},
        headers=auth_headers(user["access_token"]),
    )
    assert resp.status_code == 422
    assert "email" in resp.json()["error"]["message"].lower()
