"""Tests for TOTP Multi-Factor Authentication endpoints.

Covers the full MFA lifecycle:
  - Setup (GET /auth/mfa/setup)
  - Confirm / enable (POST /auth/mfa/confirm)
  - Disable (POST /auth/mfa/disable)
  - Admin force-reset (DELETE /auth/mfa/admin/{user_id})
  - Second-factor login (POST /auth/mfa/verify-login)
  - Full login flow: password → mfa_token → verify → access token
"""

import pyotp
import pytest

from app import models
from app.auth import create_mfa_token, hash_password


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mfa_user(db):
    """A fresh contributor with no MFA configured."""
    user = models.User(
        username="mfatestuser",
        hashed_password=hash_password("MfaPass123!"),
        role="contributor",
        is_active=True,
        email="mfatest@test.local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.delete(user)
    db.commit()


@pytest.fixture
def mfa_auth_headers(client, mfa_user):
    """Auth token for mfa_user (before MFA is enabled, so login works normally)."""
    resp = client.post("/auth/login", data={"username": "mfatestuser", "password": "MfaPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── GET /auth/mfa/setup ────────────────────────────────────────────────────────

def test_mfa_setup_returns_secret_and_qr(client, mfa_auth_headers):
    resp = client.get("/auth/mfa/setup", headers=mfa_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert len(data["secret"]) >= 16
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert "<svg" in data["qr_svg"]


def test_mfa_setup_returns_same_secret_on_repeat_call(client, mfa_auth_headers):
    """Calling setup twice before confirming should return the same secret."""
    r1 = client.get("/auth/mfa/setup", headers=mfa_auth_headers)
    r2 = client.get("/auth/mfa/setup", headers=mfa_auth_headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["secret"] == r2.json()["secret"]


def test_mfa_setup_rejects_when_already_enabled(client, db, mfa_user, mfa_auth_headers):
    mfa_user.mfa_enabled = True
    mfa_user.totp_secret = pyotp.random_base32()
    db.commit()

    resp = client.get("/auth/mfa/setup", headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "already enabled" in resp.json()["detail"]


# ── POST /auth/mfa/confirm ─────────────────────────────────────────────────────

def test_mfa_confirm_without_calling_setup_first(client, mfa_auth_headers):
    resp = client.post("/auth/mfa/confirm", json={"code": "000000"}, headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "setup" in resp.json()["detail"].lower()


def test_mfa_confirm_wrong_code(client, db, mfa_user, mfa_auth_headers):
    mfa_user.totp_secret = pyotp.random_base32()
    db.commit()

    resp = client.post("/auth/mfa/confirm", json={"code": "000000"}, headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_mfa_confirm_success(client, db, mfa_user, mfa_auth_headers):
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    db.commit()

    code = pyotp.TOTP(secret).now()
    resp = client.post("/auth/mfa/confirm", json={"code": code}, headers=mfa_auth_headers)

    assert resp.status_code == 200
    assert resp.json()["mfa_enabled"] is True
    db.refresh(mfa_user)
    assert mfa_user.mfa_enabled is True


def test_mfa_confirm_rejects_when_already_enabled(client, db, mfa_user, mfa_auth_headers):
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    mfa_user.mfa_enabled = True
    db.commit()

    code = pyotp.TOTP(secret).now()
    resp = client.post("/auth/mfa/confirm", json={"code": code}, headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "already enabled" in resp.json()["detail"]


# ── POST /auth/mfa/disable ─────────────────────────────────────────────────────

def test_mfa_disable_when_not_enabled(client, mfa_auth_headers):
    resp = client.post("/auth/mfa/disable", json={"code": "000000"}, headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "not enabled" in resp.json()["detail"]


def test_mfa_disable_wrong_code(client, db, mfa_user, mfa_auth_headers):
    mfa_user.totp_secret = pyotp.random_base32()
    mfa_user.mfa_enabled = True
    db.commit()

    resp = client.post("/auth/mfa/disable", json={"code": "000000"}, headers=mfa_auth_headers)
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_mfa_disable_success(client, db, mfa_user, mfa_auth_headers):
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    mfa_user.mfa_enabled = True
    db.commit()

    code = pyotp.TOTP(secret).now()
    resp = client.post("/auth/mfa/disable", json={"code": code}, headers=mfa_auth_headers)

    assert resp.status_code == 200
    assert resp.json()["mfa_enabled"] is False
    db.refresh(mfa_user)
    assert mfa_user.mfa_enabled is False
    assert mfa_user.totp_secret is None


# ── DELETE /auth/mfa/admin/{user_id} ──────────────────────────────────────────

def test_admin_reset_mfa_user_not_found(client, auth_headers):
    resp = client.delete("/auth/mfa/admin/99999", headers=auth_headers)
    assert resp.status_code == 404


def test_admin_reset_mfa_requires_admin(client, mfa_user, mfa_auth_headers):
    resp = client.delete(f"/auth/mfa/admin/{mfa_user.id}", headers=mfa_auth_headers)
    assert resp.status_code == 403


def test_admin_reset_mfa_clears_state_and_bumps_token_version(client, db, mfa_user, auth_headers):
    mfa_user.totp_secret = pyotp.random_base32()
    mfa_user.mfa_enabled = True
    mfa_user.token_version = 5
    db.commit()

    resp = client.delete(f"/auth/mfa/admin/{mfa_user.id}", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["mfa_enabled"] is False
    db.refresh(mfa_user)
    assert mfa_user.mfa_enabled is False
    assert mfa_user.totp_secret is None
    assert mfa_user.token_version == 6  # bumped to invalidate existing sessions


# ── POST /auth/mfa/verify-login ───────────────────────────────────────────────

def test_verify_login_rejects_garbage_token(client):
    resp = client.post(
        "/auth/mfa/verify-login",
        json={"mfa_token": "notavalidjwt", "code": "123456"},
    )
    assert resp.status_code == 401


def test_verify_login_rejects_wrong_totp_code(client, db, mfa_user):
    mfa_user.totp_secret = pyotp.random_base32()
    mfa_user.mfa_enabled = True
    db.commit()

    mfa_tok = create_mfa_token(mfa_user.id)
    resp = client.post(
        "/auth/mfa/verify-login",
        json={"mfa_token": mfa_tok, "code": "000000"},
    )
    assert resp.status_code == 401
    assert "Invalid TOTP" in resp.json()["detail"]


def test_verify_login_success_returns_jwt_pair(client, db, mfa_user):
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    mfa_user.mfa_enabled = True
    db.commit()

    mfa_tok = create_mfa_token(mfa_user.id)
    code = pyotp.TOTP(secret).now()
    resp = client.post(
        "/auth/mfa/verify-login",
        json={"mfa_token": mfa_tok, "code": code},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["role"] == "contributor"
    assert data["mfa_required"] is False


def test_verify_login_rejects_inactive_user(client, db, mfa_user):
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    mfa_user.mfa_enabled = True
    mfa_user.is_active = False
    db.commit()

    mfa_tok = create_mfa_token(mfa_user.id)
    code = pyotp.TOTP(secret).now()
    resp = client.post(
        "/auth/mfa/verify-login",
        json={"mfa_token": mfa_tok, "code": code},
    )
    assert resp.status_code == 401


# ── Full login flow ────────────────────────────────────────────────────────────

def test_full_mfa_login_flow(client, db, mfa_user):
    """Login → mfa_required + mfa_token → verify-login → usable access token."""
    secret = pyotp.random_base32()
    mfa_user.totp_secret = secret
    mfa_user.mfa_enabled = True
    db.commit()

    # Step 1: password auth — should gate on MFA, not issue a full token
    login_resp = client.post(
        "/auth/login",
        data={"username": "mfatestuser", "password": "MfaPass123!"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["mfa_required"] is True
    assert login_data["mfa_token"]
    assert login_data["access_token"] is None

    # Step 2: TOTP verification — should return real tokens
    code = pyotp.TOTP(secret).now()
    verify_resp = client.post(
        "/auth/mfa/verify-login",
        json={"mfa_token": login_data["mfa_token"], "code": code},
    )
    assert verify_resp.status_code == 200
    tokens = verify_resp.json()
    assert tokens["access_token"]
    assert tokens["mfa_required"] is False

    # Step 3: access token should be valid for authenticated endpoints
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "mfatestuser"
