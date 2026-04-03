"""Tests for OIDC / SSO Authorization Code Flow endpoints.

Covers:
  - GET /auth/oidc/status (configured / not configured)
  - GET /auth/oidc/authorize (not configured → 501; configured → 302 redirect)
  - GET /auth/oidc/callback:
      - not configured → 501
      - invalid/expired state → 400
      - IdP token exchange failure → 502
      - IdP userinfo fetch failure → 502
      - new user auto-provisioned
      - existing user found by oidc_sub
      - existing local account linked by email
      - disabled user → 403

httpx calls are mocked via unittest.mock so no real IdP is needed.
The discovery doc is pre-seeded into the module cache to avoid HTTP for that too.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.routers.oidc as oidc_module
from app import models
from app.auth import hash_password

_FAKE_DISCOVERY = {
    "authorization_endpoint": "https://idp.example.com/auth",
    "token_endpoint": "https://idp.example.com/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def oidc_env(monkeypatch):
    """Patch module-level OIDC env-var fallbacks and pre-warm the discovery cache."""
    monkeypatch.setattr(oidc_module, "_ENV_ISSUER", "https://idp.example.com")
    monkeypatch.setattr(oidc_module, "_ENV_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oidc_module, "_ENV_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(oidc_module, "_APP_BASE_URL", "https://caams.example.com")
    monkeypatch.setattr(oidc_module, "_discovery_cache", dict(_FAKE_DISCOVERY))
    monkeypatch.setattr(oidc_module, "_discovery_cache_issuer", "https://idp.example.com")
    monkeypatch.setattr(oidc_module, "_discovery_ts", time.time())


def _valid_state():
    """Generate a correctly-signed state value using the module's own logic."""
    return oidc_module._make_state()


def _httpx_mock(token_status=200, userinfo_status=200, userinfo_payload=None):
    """
    Return an AsyncMock suitable for use as an httpx.AsyncClient context manager.

    The OIDC callback makes two sequential `async with httpx.AsyncClient() as c:`
    blocks — one calling c.post() (token exchange) and one calling c.get()
    (userinfo). Both calls share the same mock instance.
    """
    if userinfo_payload is None:
        userinfo_payload = {
            "sub": "sub-default",
            "email": "default@example.com",
            "name": "Default User",
        }

    token_resp = MagicMock()
    token_resp.status_code = token_status
    token_resp.text = "upstream error" if token_status != 200 else ""
    token_resp.json.return_value = {"access_token": "idp-access-token"}

    userinfo_resp = MagicMock()
    userinfo_resp.status_code = userinfo_status
    userinfo_resp.json.return_value = userinfo_payload

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_resp)
    mock_client.get = AsyncMock(return_value=userinfo_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ── GET /auth/oidc/status ─────────────────────────────────────────────────────

def test_oidc_status_not_configured(client):
    resp = client.get("/auth/oidc/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["issuer"] is None


def test_oidc_status_configured(client, oidc_env):
    resp = client.get("/auth/oidc/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["issuer"] == "https://idp.example.com"


# ── GET /auth/oidc/authorize ──────────────────────────────────────────────────

def test_oidc_authorize_not_configured(client):
    resp = client.get("/auth/oidc/authorize", follow_redirects=False)
    assert resp.status_code == 501


def test_oidc_authorize_redirects_to_idp(client, oidc_env):
    resp = client.get("/auth/oidc/authorize", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://idp.example.com/auth")
    assert "client_id=test-client-id" in location
    assert "state=" in location
    assert "redirect_uri=" in location


# ── GET /auth/oidc/callback ───────────────────────────────────────────────────

def test_oidc_callback_not_configured(client):
    resp = client.get("/auth/oidc/callback", params={"code": "abc", "state": "x"})
    assert resp.status_code == 501


def test_oidc_callback_invalid_state(client, oidc_env):
    resp = client.get("/auth/oidc/callback", params={"code": "abc", "state": "bad.state"})
    assert resp.status_code == 400


def test_oidc_callback_expired_state(client, oidc_env):
    # Craft a state with a timestamp 11 minutes in the past (beyond the 600s window)
    import hashlib
    import hmac
    ts = str(int(time.time()) - 700)
    sig = hmac.new(
        oidc_module._SECRET_KEY.encode(), ts.encode(), hashlib.sha256
    ).hexdigest()[:24]
    old_state = f"{ts}.{sig}"

    resp = client.get("/auth/oidc/callback", params={"code": "abc", "state": old_state})
    assert resp.status_code == 400


def test_oidc_callback_token_exchange_failure(client, oidc_env):
    state = _valid_state()
    mock_client = _httpx_mock(token_status=400)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 502


def test_oidc_callback_userinfo_failure(client, oidc_env):
    state = _valid_state()
    mock_client = _httpx_mock(userinfo_status=401)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 502


def test_oidc_callback_provisions_new_user(client, db, oidc_env):
    """A user with a new sub should be created and receive CAAMS tokens."""
    state = _valid_state()
    mock_client = _httpx_mock(userinfo_payload={
        "sub": "new-sub-provisioned",
        "email": "newoidcuser@example.com",
        "name": "New OIDC User",
    })

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 200
    body = resp.text
    assert "caams_token" in body
    assert "caams_refresh_token" in body
    assert "window.location.replace" in body

    # User should now exist in the database
    user = db.query(models.User).filter(models.User.oidc_sub == "new-sub-provisioned").first()
    assert user is not None
    assert user.email == "newoidcuser@example.com"
    assert user.role == "viewer"  # CAAMS_OIDC_DEFAULT_ROLE default
    assert user.is_active is True

    # Cleanup
    db.delete(user)
    db.commit()


def test_oidc_callback_existing_user_by_sub(client, db, oidc_env):
    """Callback authenticates an existing user matched by oidc_sub."""
    existing = models.User(
        username="oidcbysubu",
        hashed_password="oidc-only",
        role="contributor",
        email="bysub@example.com",
        oidc_sub="known-sub-bysub",
        is_active=True,
    )
    db.add(existing)
    db.commit()
    db.refresh(existing)

    state = _valid_state()
    mock_client = _httpx_mock(userinfo_payload={
        "sub": "known-sub-bysub",
        "email": "bysub@example.com",
    })

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 200
    assert "caams_token" in resp.text

    db.delete(existing)
    db.commit()


def test_oidc_callback_links_existing_local_account_by_email(client, db, oidc_env):
    """Callback links a local account to SSO when email matches but no oidc_sub set."""
    local_user = models.User(
        username="locallinkuser",
        hashed_password=hash_password("LocalPass123!"),
        role="viewer",
        email="locallink@example.com",
        is_active=True,
    )
    db.add(local_user)
    db.commit()
    db.refresh(local_user)
    assert local_user.oidc_sub is None

    state = _valid_state()
    mock_client = _httpx_mock(userinfo_payload={
        "sub": "brand-new-sub-link",
        "email": "locallink@example.com",
    })

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 200
    db.refresh(local_user)
    assert local_user.oidc_sub == "brand-new-sub-link"

    db.delete(local_user)
    db.commit()


def test_oidc_callback_disabled_user_rejected(client, db, oidc_env):
    """A disabled user should receive a 403, not a token."""
    disabled = models.User(
        username="disabledoidcu",
        hashed_password="oidc-only",
        role="viewer",
        email="disabledoidc@example.com",
        oidc_sub="disabled-sub-oidc",
        is_active=False,
    )
    db.add(disabled)
    db.commit()
    db.refresh(disabled)

    state = _valid_state()
    mock_client = _httpx_mock(userinfo_payload={
        "sub": "disabled-sub-oidc",
        "email": "disabledoidc@example.com",
    })

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 403
    assert "caams_token" not in resp.text

    db.delete(disabled)
    db.commit()


def test_oidc_callback_no_sub_in_userinfo(client, db, oidc_env):
    """If IdP returns no sub, callback should return 502."""
    state = _valid_state()
    mock_client = _httpx_mock(userinfo_payload={"email": "nosub@example.com"})  # no "sub"

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 502


def test_oidc_callback_username_collision_resolves(client, db, oidc_env):
    """When a derived username collides, a numeric suffix should be appended."""
    # Pre-create a user whose username matches what would be derived from the email
    collision = models.User(
        username="collision",
        hashed_password=hash_password("Pass123!"),
        role="viewer",
        email="other@example.com",
        is_active=True,
    )
    db.add(collision)
    db.commit()

    state = _valid_state()
    # email "collision@example.com" → base username "collision" → already taken → "collision1"
    mock_client = _httpx_mock(userinfo_payload={
        "sub": "collision-sub-xyz",
        "email": "collision@example.com",
    })

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/auth/oidc/callback", params={"code": "code123", "state": state})

    assert resp.status_code == 200

    new_user = db.query(models.User).filter(models.User.oidc_sub == "collision-sub-xyz").first()
    assert new_user is not None
    assert new_user.username == "collision1"

    db.delete(new_user)
    db.delete(collision)
    db.commit()
