"""OIDC / SSO endpoints — Authorization Code Flow.

Configuration priority (highest first):
  1. Database (site_settings row) — set via Admin → System → SSO
  2. Environment variables — CAAMS_OIDC_ISSUER, CAAMS_OIDC_CLIENT_ID,
     CAAMS_OIDC_CLIENT_SECRET, CAAMS_OIDC_DEFAULT_ROLE
  3. Unconfigured — SSO button hidden on login page

CAAMS_APP_BASE_URL is still env-var only (it's a general app setting used
by other features too).
"""

import hashlib
import hmac
import json
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.auth import create_access_token, create_refresh_token
from app.crypto import decrypt_field
from app.database import get_db
from app.limiter import limiter
from app.logging_config import get_logger
from app.routers.audit_log import log_event

router = APIRouter(prefix="/auth/oidc", tags=["sso"])
log = get_logger("caams.oidc")

# Env-var fallbacks (used when DB has no OIDC config)
_ENV_ISSUER        = os.environ.get("CAAMS_OIDC_ISSUER", "")
_ENV_CLIENT_ID     = os.environ.get("CAAMS_OIDC_CLIENT_ID", "")
_ENV_CLIENT_SECRET = os.environ.get("CAAMS_OIDC_CLIENT_SECRET", "")
_ENV_DEFAULT_ROLE  = os.environ.get("CAAMS_OIDC_DEFAULT_ROLE", "viewer")
_APP_BASE_URL      = os.environ.get("CAAMS_APP_BASE_URL", "")
_SECRET_KEY        = os.environ.get("CAAMS_SECRET_KEY", "")

_discovery_cache: Optional[dict] = None
_discovery_cache_issuer: str = ""
_discovery_ts: float = 0
_CACHE_TTL = 3600  # re-fetch discovery doc every hour


def bust_discovery_cache() -> None:
    """Invalidate the cached discovery document (call after config changes)."""
    global _discovery_cache, _discovery_cache_issuer, _discovery_ts
    _discovery_cache = None
    _discovery_cache_issuer = ""
    _discovery_ts = 0


def get_oidc_config(db=None) -> dict:
    """Return effective OIDC settings, preferring DB config over env vars.

    Returns a dict with keys: issuer, client_id, client_secret, default_role,
    source ('db' | 'env' | 'none').
    """
    row = None
    try:
        if db is not None:
            row = db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
        else:
            from app.database import SessionLocal
            _db = SessionLocal()
            try:
                row = _db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
            finally:
                _db.close()
    except Exception as exc:
        log.warning("Could not read OIDC config from DB, using env vars: %s", exc)

    if row and row.oidc_issuer:
        return {
            "issuer":        row.oidc_issuer,
            "client_id":     row.oidc_client_id or "",
            "client_secret": decrypt_field(row.oidc_client_secret or ""),
            "default_role":  row.oidc_default_role or "viewer",
            "source":        "db",
        }

    return {
        "issuer":        _ENV_ISSUER,
        "client_id":     _ENV_CLIENT_ID,
        "client_secret": _ENV_CLIENT_SECRET,
        "default_role":  _ENV_DEFAULT_ROLE,
        "source":        "env" if _ENV_ISSUER else "none",
    }


def _redirect_uri() -> str:
    base = _APP_BASE_URL.rstrip("/")
    return f"{base}/auth/oidc/callback"


async def _discovery(issuer: str) -> dict:
    global _discovery_cache, _discovery_cache_issuer, _discovery_ts
    if (
        _discovery_cache
        and _discovery_cache_issuer == issuer
        and time.time() - _discovery_ts < _CACHE_TTL
    ):
        return _discovery_cache
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        r.raise_for_status()
        _discovery_cache = r.json()
        _discovery_cache_issuer = issuer
        _discovery_ts = time.time()
        return _discovery_cache


def _make_state() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(_SECRET_KEY.encode(), ts.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{ts}.{sig}"


def _verify_state(state: str) -> bool:
    try:
        ts_str, sig = state.split(".", 1)
        if time.time() - int(ts_str) > 600:
            return False
        expected = hmac.new(_SECRET_KEY.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:24]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


@router.get("/status")
def oidc_status(db: Session = Depends(get_db)):
    """Return whether SSO is configured (safe to call from the login page)."""
    cfg = get_oidc_config(db)
    configured = bool(cfg["issuer"] and cfg["client_id"] and cfg["client_secret"])
    return {
        "configured":    configured,
        "issuer":        cfg["issuer"]       if configured else None,
        "client_id":     cfg["client_id"]    if configured else None,
        "default_role":  cfg["default_role"] if configured else None,
        "callback_url":  _redirect_uri()     if _APP_BASE_URL else None,
        "source":        cfg["source"],
    }


@router.get("/authorize")
@limiter.limit("20/hour")
async def oidc_authorize(request: Request, db: Session = Depends(get_db)):
    """Redirect the browser to the IdP's authorization endpoint."""
    cfg = get_oidc_config(db)
    if not (cfg["issuer"] and cfg["client_id"] and cfg["client_secret"]):
        return HTMLResponse("<p>SSO not configured.</p>", status_code=501)
    disc = await _discovery(cfg["issuer"])
    state = _make_state()
    from urllib.parse import quote
    params = (
        f"?response_type=code"
        f"&client_id={quote(cfg['client_id'])}"
        f"&redirect_uri={quote(_redirect_uri())}"
        f"&scope=openid%20email%20profile"
        f"&state={state}"
    )
    return RedirectResponse(disc["authorization_endpoint"] + params, status_code=302)


@router.get("/callback")
@limiter.limit("20/hour")
async def oidc_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    """Handle the IdP callback: exchange code for tokens, provision user, issue CAAMS JWT."""
    cfg = get_oidc_config(db)
    if not (cfg["issuer"] and cfg["client_id"] and cfg["client_secret"]):
        return HTMLResponse("<p>SSO not configured.</p>", status_code=501)
    if not _verify_state(state):
        return HTMLResponse("<p>Invalid or expired SSO state. Please try again.</p>", status_code=400)

    try:
        disc = await _discovery(cfg["issuer"])
    except Exception as exc:
        log.error("OIDC discovery failed: %s", exc)
        return HTMLResponse("<p>SSO provider unreachable. Contact your administrator.</p>", status_code=502)

    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            tr = await client.post(
                disc["token_endpoint"],
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  _redirect_uri(),
                    "client_id":     cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                },
            )
    except httpx.HTTPError as exc:
        log.error("OIDC token exchange network error: %s", exc)
        return HTMLResponse("<p>SSO token exchange failed. Contact your administrator.</p>", status_code=502)
    if tr.status_code != 200:
        log.error("OIDC token exchange failed: %s", tr.text[:200])
        return HTMLResponse("<p>SSO token exchange failed. Contact your administrator.</p>", status_code=502)
    token_data = tr.json()

    # Fetch user info from IdP
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ur = await client.get(
                disc["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
    except httpx.HTTPError as exc:
        log.error("OIDC userinfo network error: %s", exc)
        return HTMLResponse("<p>SSO user info fetch failed. Contact your administrator.</p>", status_code=502)
    if ur.status_code != 200:
        return HTMLResponse("<p>SSO user info fetch failed. Contact your administrator.</p>", status_code=502)
    userinfo = ur.json()

    oidc_sub = userinfo.get("sub", "")
    email    = userinfo.get("email", "")
    name     = (userinfo.get("name") or userinfo.get("preferred_username") or
                email.split("@")[0] or oidc_sub[:20])

    if not oidc_sub:
        return HTMLResponse("<p>SSO did not return a subject identifier.</p>", status_code=502)

    # Find or create user
    user = db.query(models.User).filter(models.User.oidc_sub == oidc_sub).first()
    if not user and email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.oidc_sub = oidc_sub  # link existing local account to SSO

    if not user:
        # Auto-provision: derive a unique username from email
        base = (email.split("@")[0] or name).lower().replace(" ", ".")[:32]
        username = base
        i = 1
        while db.query(models.User).filter(models.User.username == username).first():
            username = f"{base}{i}"
            i += 1
        user = models.User(
            username=username,
            hashed_password="oidc-only",
            role=cfg["default_role"],
            full_name=name,
            email=email,
            oidc_sub=oidc_sub,
            is_active=True,
        )
        db.add(user)
        log.info("OIDC auto-provisioned | username=%s sub=%.8s", username, oidc_sub)

    if not user.is_active:
        return HTMLResponse(
            "<html><body><p>Your account is disabled. Contact your administrator.</p></body></html>",
            status_code=403,
        )

    try:
        db.commit()
    except IntegrityError:
        # Two concurrent logins raced to create the same user — re-fetch the winner.
        db.rollback()
        user = (
            db.query(models.User).filter(models.User.oidc_sub == oidc_sub).first()
            or db.query(models.User).filter(models.User.email == email).first()
        )
        if not user:
            log.error("OIDC auto-provision race: could not recover user sub=%.8s", oidc_sub)
            return HTMLResponse("<p>SSO login failed. Please try again.</p>", status_code=500)
    db.refresh(user)
    log_event(db, user=user, action="SSO_LOGIN", resource_type="user",
              resource_id=str(user.id), details={"issuer": cfg["issuer"]})

    tv = user.token_version or 0
    access  = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})

    html = (
        "<!DOCTYPE html><html><head><title>Signing in…</title></head><body>"
        "<script>"
        f"localStorage.setItem('caams_token',{json.dumps(access)});"
        f"localStorage.setItem('caams_refresh_token',{json.dumps(refresh)});"
        "window.location.replace('/');"
        "</script>"
        "<p>Signing in, please wait…</p>"
        "</body></html>"
    )
    return HTMLResponse(html)
