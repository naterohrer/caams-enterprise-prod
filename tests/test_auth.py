"""Integration tests for authentication and user-management endpoints."""



# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------


def test_login_success(client, admin_user):
    resp = client.post("/auth/login", data={"username": "testadmin", "password": "TestPass123!"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"] != ""
    assert body["role"] == "admin"


def test_login_wrong_password(client, admin_user):
    resp = client.post("/auth/login", data={"username": "testadmin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(client, admin_user):
    resp = client.post("/auth/login", data={"username": "nobody", "password": "pw"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


def test_me_returns_current_user(client, admin_user, auth_headers):
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "testadmin"


def test_me_unauthenticated(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/setup-needed
# ---------------------------------------------------------------------------


def test_setup_needed_false_when_users_exist(client, admin_user):
    resp = client.get("/auth/setup-needed")
    assert resp.status_code == 200
    assert resp.json()["needed"] is False


# ---------------------------------------------------------------------------
# /auth/users  (admin-only CRUD)
# ---------------------------------------------------------------------------


def test_list_users_requires_admin(client, auth_headers):
    resp = client.get("/auth/users", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(u["username"] == "testadmin" for u in data)


def test_list_users_unauthenticated(client, admin_user):
    resp = client.get("/auth/users")
    assert resp.status_code == 401


def test_create_user_and_delete(client, auth_headers, db):
    # Create
    resp = client.post(
        "/auth/users",
        json={"username": "newviewer", "password": "Pass1234567!", "role": "viewer",
              "full_name": "New Viewer", "email": "viewer@test.local"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    assert resp.json()["role"] == "viewer"

    # Confirm it appears in list
    list_resp = client.get("/auth/users", headers=auth_headers)
    usernames = [u["username"] for u in list_resp.json()]
    assert "newviewer" in usernames

    # Delete
    del_resp = client.delete(f"/auth/users/{user_id}", headers=auth_headers)
    assert del_resp.status_code == 204


def test_create_duplicate_user_returns_409(client, auth_headers, admin_user):
    resp = client.post(
        "/auth/users",
        json={"username": "testadmin", "password": "AnotherPass1!", "role": "viewer",
              "full_name": "", "email": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_update_user_role(client, auth_headers, db):
    # Create a user to update
    resp = client.post(
        "/auth/users",
        json={"username": "roletest", "password": "Pass1234567!", "role": "viewer",
              "full_name": "", "email": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    patch_resp = client.patch(
        f"/auth/users/{user_id}",
        json={"role": "contributor"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["role"] == "contributor"

    # Clean up
    client.delete(f"/auth/users/{user_id}", headers=auth_headers)


def test_cannot_delete_self(client, auth_headers, admin_user):
    resp = client.delete(f"/auth/users/{admin_user.id}", headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /auth/directory  (viewer+)
# ---------------------------------------------------------------------------


def test_directory_returns_active_users(client, auth_headers, admin_user):
    resp = client.get("/auth/directory", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(u["username"] == "testadmin" for u in data)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def test_security_headers_present(client, admin_user):
    resp = client.get("/auth/setup-needed")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"


# ---------------------------------------------------------------------------
# /auth/refresh — JWT refresh token flow
# ---------------------------------------------------------------------------


def test_refresh_returns_new_tokens(client, admin_user):
    """A valid refresh token returns a fresh access + refresh token pair."""
    login = client.post("/auth/login", data={"username": "testadmin", "password": "TestPass123!"})
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]
    assert refresh_token

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["access_token"] != login.json()["access_token"]  # new token issued


def test_refresh_rejects_access_token(client, admin_user):
    """An access token must not be accepted by the refresh endpoint."""
    login = client.post("/auth/login", data={"username": "testadmin", "password": "TestPass123!"})
    access_token = login.json()["access_token"]

    resp = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


def test_refresh_rejects_invalid_token(client, admin_user):
    resp = client.post("/auth/refresh", json={"refresh_token": "garbage.token.value"})
    assert resp.status_code == 401


def test_access_token_rejected_as_refresh(client, admin_user, auth_headers):
    """A refresh token must NOT work as a Bearer access token for API calls."""
    login = client.post("/auth/login", data={"username": "testadmin", "password": "TestPass123!"})
    refresh_token = login.json()["refresh_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/users/invite + /auth/invite/accept — invite flow
# ---------------------------------------------------------------------------


def test_invite_user_full_flow(client, auth_headers):
    """Admin invites a user; user accepts invite with their own password."""
    # 1. Admin creates invite
    resp = client.post(
        "/auth/users/invite",
        json={"username": "invited_user", "role": "viewer",
              "full_name": "Invited User", "email": "invite@test.local"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "invited_user"
    assert "invite_token" in body
    assert body["expires_hours"] == 72
    raw_token = body["invite_token"]

    # 2. Invited user cannot log in before accepting
    login_resp = client.post(
        "/auth/login", data={"username": "invited_user", "password": "anything"}
    )
    assert login_resp.status_code == 403

    # 3. User accepts the invite and sets their password
    accept_resp = client.post(
        "/auth/invite/accept",
        json={"token": raw_token, "password": "MyNewPass1234567!"},
    )
    assert accept_resp.status_code == 200
    tokens = accept_resp.json()
    assert "access_token" in tokens
    assert tokens["role"] == "viewer"

    # 4. Token is now consumed — second accept must fail
    reuse_resp = client.post(
        "/auth/invite/accept",
        json={"token": raw_token, "password": "AnotherPass1!"},
    )
    assert reuse_resp.status_code == 400

    # 5. User can now log in normally
    login_resp2 = client.post(
        "/auth/login", data={"username": "invited_user", "password": "MyNewPass1234567!"}
    )
    assert login_resp2.status_code == 200


def test_invite_bad_token(client, admin_user):
    resp = client.post(
        "/auth/invite/accept",
        json={"token": "totallyfaketoken", "password": "SomePass1234567!"},
    )
    assert resp.status_code == 400


def test_invite_duplicate_username(client, auth_headers, admin_user):
    resp = client.post(
        "/auth/users/invite",
        json={"username": "testadmin", "role": "viewer", "full_name": "", "email": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_invite_requires_admin(client, auth_headers, db):
    """A viewer token must not be able to create invites."""
    from app import models
    from app.auth import hash_password
    viewer = models.User(
        username="plain_viewer", hashed_password=hash_password("Pass1234567!"),
        role="viewer", is_active=True,
    )
    db.add(viewer)
    db.commit()

    login = client.post("/auth/login", data={"username": "plain_viewer", "password": "Pass1234567!"})
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(
        "/auth/users/invite",
        json={"username": "shouldfail", "role": "viewer", "full_name": "", "email": ""},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
