"""Security / authorization tests.

Verifies the core isolation guarantees:
  * User A cannot access User B's family, policies, documents, or chunks.
  * Viewers cannot perform write actions.
  * Signed document URLs are required for unauthenticated file access.
"""

from __future__ import annotations

from tests.conftest import (
    auth_headers,
    create_family,
    create_policy,
    make_pdf_bytes,
    register,
)


def _two_users(client):
    a = register(client, "user_a@example.com", "User A")
    b = register(client, "user_b@example.com", "User B")
    fa = create_family(client, a["access_token"], "Family A")
    fb = create_family(client, b["access_token"], "Family B")
    return a, b, fa, fb


def test_user_cannot_read_other_family(client):
    a, b, fa, fb = _two_users(client)
    resp = client.get(
        f"/api/v1/families/{fb['id']}", headers=auth_headers(a["access_token"])
    )
    # 404 (not 403) so family existence is not disclosed.
    assert resp.status_code == 404


def test_user_cannot_list_other_family_members(client):
    a, b, fa, fb = _two_users(client)
    resp = client.get(
        f"/api/v1/families/{fb['id']}/members",
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 404


def test_user_cannot_access_other_policy(client):
    a, b, fa, fb = _two_users(client)
    policy = create_policy(client, b["access_token"], fb["id"])
    resp = client.get(
        f"/api/v1/families/{fa['id']}/policies/{policy['id']}",
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 404


def test_user_cannot_create_policy_in_other_family(client):
    a, b, fa, fb = _two_users(client)
    resp = client.post(
        f"/api/v1/families/{fb['id']}/policies",
        json={
            "family_id": fb["id"],
            "policy_type": "life",
            "insurer": "X",
            "policy_number": "N1",
        },
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 404


def test_user_cannot_access_other_document(client):
    a, b, fa, fb = _two_users(client)
    pdf = make_pdf_bytes("Policy Number: ABC-123\nInsurer: Acme")
    up = client.post(
        f"/api/v1/families/{fb['id']}/documents",
        files={"file": ("p.pdf", pdf, "application/pdf")},
        headers=auth_headers(b["access_token"]),
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    resp = client.get(
        f"/api/v1/families/{fa['id']}/documents/{doc_id}/download",
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 404


def test_user_cannot_retrieve_other_family_chunks_via_assistant(client):
    a, b, fa, fb = _two_users(client)
    pdf = make_pdf_bytes(
        "Policy Number: SECRET-999\nInsurer: SecretInsure\n"
        "Sum Insured: 1000000\nWaiting Period: 24 months"
    )
    up = client.post(
        f"/api/v1/families/{fb['id']}/documents",
        files={"file": ("secret.pdf", pdf, "application/pdf")},
        headers=auth_headers(b["access_token"]),
    )
    assert up.status_code == 201
    # User A asks about a secret keyword present only in B's document.
    resp = client.post(
        "/api/v1/assistant/ask",
        json={"family_id": fa["id"], "question": "What is the waiting period?"},
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Must not leak B's content.
    assert "SECRET-999" not in body["answer"]
    assert "SecretInsure" not in body["answer"]


def test_assistant_rejects_cross_family_query(client):
    a, b, fa, fb = _two_users(client)
    resp = client.post(
        "/api/v1/assistant/ask",
        json={"family_id": fb["id"], "question": "summary"},
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 404


def test_search_never_returns_other_family_rows(client):
    """A user's search must only ever return rows from their own family."""
    a, b, fa, fb = _two_users(client)
    create_policy(
        client,
        b["access_token"],
        fb["id"],
        insurer="SecretInsure",
        policy_number="SECRET-777",
    )
    client.post(
        f"/api/v1/families/{fb['id']}/members",
        json={"name": "Secret Person", "relationship": "father"},
        headers=auth_headers(b["access_token"]),
    )

    # User A searches their own family for a term that only exists in family B.
    resp = client.get(
        f"/api/v1/families/{fa['id']}/search?q=secret",
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert "SECRET-777" not in resp.text
    assert "Secret Person" not in resp.text

    # User B can find their own row.
    own = client.get(
        f"/api/v1/families/{fb['id']}/search?q=secret",
        headers=auth_headers(b["access_token"]),
    )
    assert own.status_code == 200
    assert {r["kind"] for r in own.json()["results"]} == {"policy", "family_member"}


def test_assistant_search_tool_is_family_scoped(client):
    """The assistant's record lookup must not surface another family's rows."""
    a, b, fa, fb = _two_users(client)
    create_policy(
        client,
        b["access_token"],
        fb["id"],
        insurer="SecretInsure",
        policy_number="SECRET-777",
    )

    resp = client.post(
        "/api/v1/assistant/ask",
        json={"family_id": fa["id"], "question": "find policy number SECRET-777"},
        headers=auth_headers(a["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matches"] == []
    assert body["grounded"] is False
    # No record data from the other family leaks into the answer.
    assert "SecretInsure" not in body["answer"]

    # The owner can find it, and it is returned as a linked record.
    own = client.post(
        "/api/v1/assistant/ask",
        json={"family_id": fb["id"], "question": "find policy number SECRET-777"},
        headers=auth_headers(b["access_token"]),
    )
    assert own.status_code == 200
    own_body = own.json()
    assert own_body["grounded"] is True
    assert [m["kind"] for m in own_body["matches"]] == ["policy"]


def test_viewer_cannot_write(client):
    a, b, fa, fb = _two_users(client)
    # Link user B into family A as a viewer.
    invite = client.post(
        f"/api/v1/families/{fa['id']}/invites",
        json={"email": "user_b@example.com", "role": "viewer"},
        headers=auth_headers(a["access_token"]),
    )
    assert invite.status_code == 201, invite.text

    # Viewer can read.
    read = client.get(
        f"/api/v1/families/{fa['id']}/policies",
        headers=auth_headers(b["access_token"]),
    )
    assert read.status_code == 200

    # Viewer cannot create a policy.
    write = client.post(
        f"/api/v1/families/{fa['id']}/policies",
        json={
            "family_id": fa["id"],
            "policy_type": "life",
            "insurer": "X",
            "policy_number": "N2",
        },
        headers=auth_headers(b["access_token"]),
    )
    assert write.status_code == 403

    # Viewer cannot add members.
    add_member = client.post(
        f"/api/v1/families/{fa['id']}/members",
        json={"name": "Sneaky", "relationship": "other"},
        headers=auth_headers(b["access_token"]),
    )
    assert add_member.status_code == 403


def test_viewer_cannot_read_audit_logs(client):
    a, b, fa, fb = _two_users(client)
    client.post(
        f"/api/v1/families/{fa['id']}/invites",
        json={"email": "user_b@example.com", "role": "viewer"},
        headers=auth_headers(a["access_token"]),
    )
    resp = client.get(
        f"/api/v1/families/{fa['id']}/audit-logs",
        headers=auth_headers(b["access_token"]),
    )
    assert resp.status_code == 403


def test_signed_url_required_for_anonymous_file_access(client):
    a, b, fa, fb = _two_users(client)
    pdf = make_pdf_bytes("Policy Number: XYZ-1")
    up = client.post(
        f"/api/v1/families/{fa['id']}/documents",
        files={"file": ("p.pdf", pdf, "application/pdf")},
        headers=auth_headers(a["access_token"]),
    )
    doc_id = up.json()["id"]

    # Forged signature must fail.
    bad = client.get(
        "/api/v1/documents/file?key=whatever&expires=9999999999&signature=deadbeef"
    )
    assert bad.status_code == 403

    # A real signed URL works.
    signed = client.post(
        f"/api/v1/families/{fa['id']}/documents/{doc_id}/signed-url",
        headers=auth_headers(a["access_token"]),
    )
    assert signed.status_code == 200
    url = signed.json()["url"]
    ok = client.get(url)
    assert ok.status_code == 200
    assert ok.content == pdf
