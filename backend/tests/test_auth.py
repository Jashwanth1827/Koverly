"""Unit tests for authentication and password handling."""

from __future__ import annotations

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import auth_headers, register


def test_password_hash_roundtrip():
    hashed = hash_password("Passw0rd!")
    assert hashed != "Passw0rd!"
    assert verify_password("Passw0rd!", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["typ"] == "access"


def test_register_and_login(client):
    data = register(client, "alice@example.com", "Alice")
    assert data["user"]["email"] == "alice@example.com"
    assert data["access_token"]

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "Passw0rd!"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "alice@example.com"


def test_duplicate_email_rejected(client):
    register(client, "bob@example.com", "Bob")
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "full_name": "Bob2", "password": "Passw0rd!"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_IN_USE"


def test_weak_password_rejected(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "full_name": "W", "password": "password"},
    )
    assert resp.status_code == 422


def test_login_wrong_password(client):
    register(client, "carol@example.com", "Carol")
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "Wrong123!"},
    )
    assert resp.status_code == 401
    # No user-enumeration signal.
    assert "incorrect" in resp.json()["error"]["message"].lower()


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_user(client):
    data = register(client, "dave@example.com", "Dave")
    resp = client.get("/api/v1/auth/me", headers=auth_headers(data["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["email"] == "dave@example.com"


def test_invalid_token_rejected(client):
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401
