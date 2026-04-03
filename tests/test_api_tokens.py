"""Tests for API token management endpoints."""


def test_list_tokens_empty(client, auth_headers):
    r = client.get("/api-tokens", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_tokens_unauthenticated(client):
    r = client.get("/api-tokens")
    assert r.status_code == 401


def test_create_token_returns_raw_token(client, auth_headers):
    r = client.post("/api-tokens", headers=auth_headers, json={
        "name": "CI Pipeline Token", "expires_at": None, "scopes": [],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "CI Pipeline Token"
    assert "token" in data  # raw token only returned at creation
    assert data["is_active"] is True
    assert data["prefix"] is not None
    token_id = data["id"]

    # Clean up
    client.delete(f"/api-tokens/{token_id}", headers=auth_headers)


def test_create_and_revoke_token(client, auth_headers):
    r = client.post("/api-tokens", headers=auth_headers, json={
        "name": "RevokableToken", "expires_at": None, "scopes": [],
    })
    assert r.status_code == 201
    token_id = r.json()["id"]

    r = client.delete(f"/api-tokens/{token_id}", headers=auth_headers)
    assert r.status_code == 204


def test_revoke_nonexistent_token_returns_404(client, auth_headers):
    r = client.delete("/api-tokens/999999", headers=auth_headers)
    assert r.status_code == 404


def test_raw_token_can_authenticate(client, auth_headers):
    r = client.post("/api-tokens", headers=auth_headers, json={
        "name": "AuthTestToken", "expires_at": None, "scopes": [],
    })
    assert r.status_code == 201
    raw_token = r.json()["token"]
    token_id = r.json()["id"]

    # Use the raw API token as a Bearer token
    api_token_headers = {"Authorization": f"Bearer {raw_token}"}
    r = client.get("/tools", headers=api_token_headers)
    assert r.status_code == 200

    # Clean up
    client.delete(f"/api-tokens/{token_id}", headers=auth_headers)


def test_token_appears_in_list(client, auth_headers):
    r = client.post("/api-tokens", headers=auth_headers, json={
        "name": "ListCheckToken", "expires_at": None, "scopes": [],
    })
    token_id = r.json()["id"]

    r = client.get("/api-tokens", headers=auth_headers)
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert token_id in ids

    # Clean up
    client.delete(f"/api-tokens/{token_id}", headers=auth_headers)


def test_create_token_requires_admin(client, auth_headers, db):
    """Contributor-level users should not be able to create tokens."""
    from app import models
    from app.auth import hash_password

    contrib = models.User(
        username="contrib_token_test",
        hashed_password=hash_password("Pass1234567!"),
        role="contributor",
        is_active=True,
    )
    db.add(contrib)
    db.commit()
    db.refresh(contrib)

    # Log in as contributor
    r = client.post("/auth/login", data={
        "username": "contrib_token_test", "password": "Pass1234567!",
    })
    contrib_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/api-tokens", headers=contrib_headers, json={
        "name": "ShouldFail", "expires_at": None, "scopes": [],
    })
    assert r.status_code == 403

    db.delete(contrib)
    db.commit()
