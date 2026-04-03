"""Admin system endpoints — SMTP config, OIDC config, backup status, system info."""

import os
import pathlib
import time

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import models
from app.auth import require_admin
from app.crypto import encrypt_field
from app.database import get_db
from app.email import get_smtp_status, send_test_email

router = APIRouter(prefix="/admin", tags=["admin"])

# Backup files are written by the pg_backup Docker service into a shared
# named volume mounted at /app/backups (read-only inside the CAAMS container).
_BACKUP_DIR = pathlib.Path(os.environ.get("CAAMS_BACKUP_DIR", "/app/backups"))


# ── SMTP status (read-only, used by the status card) ─────────────────────────

@router.get("/smtp/status")
def smtp_status(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Return current effective SMTP configuration (password omitted)."""
    return get_smtp_status(db)


# ── SMTP config (read/write for the settings form) ───────────────────────────

class SmtpConfigIn(BaseModel):
    host: str
    port: int = 587
    from_addr: str
    user: str = ""
    password: str | None = None  # None = keep existing password; "" = clear it
    use_tls: bool = True

    @field_validator("host")
    @classmethod
    def _valid_host(cls, v):
        if not v or not v.strip():
            raise ValueError("host must not be empty")
        return v.strip()

    @field_validator("from_addr")
    @classmethod
    def _valid_from_addr(cls, v):
        v = v.strip()
        if not v or "@" not in v:
            raise ValueError("from_addr must be a valid email address")
        return v

    @field_validator("port")
    @classmethod
    def _valid_port(cls, v):
        if not (1 <= v <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return v


@router.get("/smtp/config")
def get_smtp_config(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Return current SMTP configuration for the settings form.

    Includes a has_password flag instead of the actual password value.
    source is 'db' if saved via the UI, 'env' if from environment variables,
    or 'none' if not configured.
    """
    status = get_smtp_status(db)
    row = db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
    has_password = bool(row and row.smtp_password) if status["source"] == "db" else bool(
        os.environ.get("CAAMS_SMTP_PASSWORD", "")
    )
    return {**status, "has_password": has_password}


@router.put("/smtp/config")
def update_smtp_config(
    payload: SmtpConfigIn,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Save SMTP settings to the database.

    These values take precedence over environment variables immediately —
    no restart required.  Omit password (or pass null) to keep the existing
    saved password unchanged.  Pass an empty string to clear the password.
    """
    row = models.SiteSettings.get_or_create(db)
    row.smtp_host = payload.host.strip()
    row.smtp_port = payload.port
    row.smtp_from = payload.from_addr.strip()
    row.smtp_user = payload.user.strip()
    row.smtp_use_tls = payload.use_tls
    if payload.password is not None:
        row.smtp_password = encrypt_field(payload.password)  # "" stored as-is; non-empty encrypted
    db.commit()
    return get_smtp_status(db)


@router.delete("/smtp/config")
def clear_smtp_config(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Clear DB-stored SMTP settings, reverting to environment variables."""
    row = db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
    if row:
        row.smtp_host = ""
        row.smtp_port = 587
        row.smtp_from = ""
        row.smtp_user = ""
        row.smtp_password = ""
        row.smtp_use_tls = True
        db.commit()
    return get_smtp_status(db)


# ── SMTP test ─────────────────────────────────────────────────────────────────

@router.post("/smtp/test")
def smtp_test(
    to: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Send a test email to verify SMTP settings — admin only."""
    if not to or "@" not in to:
        raise HTTPException(status_code=400, detail="A valid 'to' email address is required")
    success, error = send_test_email(to, db=db)
    if not success:
        raise HTTPException(status_code=502, detail=error or "Failed to send test email")
    return {"sent": True}


# ── OIDC / SSO config ────────────────────────────────────────────────────────

class OidcConfigIn(BaseModel):
    issuer: str
    client_id: str
    client_secret: str | None = None  # None = keep existing; "" = clear
    default_role: str = "viewer"

    @field_validator("issuer")
    @classmethod
    def _valid_issuer(cls, v):
        v = v.strip().rstrip("/")
        if not v or not v.startswith(("http://", "https://")):
            raise ValueError("issuer must be a valid URL starting with http:// or https://")
        return v

    @field_validator("client_id")
    @classmethod
    def _valid_client_id(cls, v):
        if not v or not v.strip():
            raise ValueError("client_id must not be empty")
        return v.strip()

    @field_validator("default_role")
    @classmethod
    def _valid_role(cls, v):
        if v not in ("admin", "contributor", "viewer", "auditor"):
            raise ValueError("default_role must be admin, contributor, viewer, or auditor")
        return v


def _oidc_status_response(db: Session) -> dict:
    from app.routers.oidc import get_oidc_config, _APP_BASE_URL, _redirect_uri
    cfg = get_oidc_config(db)
    configured = bool(cfg["issuer"] and cfg["client_id"] and cfg["client_secret"])
    row = db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
    has_secret = bool(row and row.oidc_client_secret) if cfg["source"] == "db" else bool(
        os.environ.get("CAAMS_OIDC_CLIENT_SECRET", "")
    )
    return {
        "configured":    configured,
        "issuer":        cfg["issuer"]       or None,
        "client_id":     cfg["client_id"]    or None,
        "default_role":  cfg["default_role"],
        "source":        cfg["source"],
        "has_secret":    has_secret,
        "callback_url":  _redirect_uri() if _APP_BASE_URL else None,
    }


@router.get("/oidc/config")
def get_oidc_config_endpoint(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Return current OIDC configuration for the settings form (secret omitted)."""
    return _oidc_status_response(db)


@router.put("/oidc/config")
def update_oidc_config(
    payload: OidcConfigIn,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Save OIDC settings to the database.

    Takes effect immediately — no restart required.  Pass client_secret=null
    to keep the existing saved secret, or an empty string to clear it.
    """
    from app.routers.oidc import bust_discovery_cache
    row = models.SiteSettings.get_or_create(db)
    row.oidc_issuer       = payload.issuer
    row.oidc_client_id    = payload.client_id
    row.oidc_default_role = payload.default_role
    if payload.client_secret is not None:
        row.oidc_client_secret = encrypt_field(payload.client_secret)
    db.commit()
    bust_discovery_cache()
    return _oidc_status_response(db)


@router.delete("/oidc/config")
def clear_oidc_config(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Clear DB-stored OIDC settings, reverting to environment variables."""
    from app.routers.oidc import bust_discovery_cache
    row = db.query(models.SiteSettings).filter(models.SiteSettings.id == 1).first()
    if row:
        row.oidc_issuer        = ""
        row.oidc_client_id     = ""
        row.oidc_client_secret = ""
        row.oidc_default_role  = "viewer"
        db.commit()
    bust_discovery_cache()
    return _oidc_status_response(db)


@router.post("/oidc/test")
async def oidc_test(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Verify OIDC config by fetching the IdP discovery document."""
    from app.routers.oidc import get_oidc_config, bust_discovery_cache
    cfg = get_oidc_config(db)
    if not cfg["issuer"]:
        raise HTTPException(status_code=400, detail="OIDC issuer is not configured")
    url = f"{cfg['issuer'].rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            doc = r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"IdP returned HTTP {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    # Bust cache so the freshly-fetched doc is used on next login
    bust_discovery_cache()
    return {
        "ok":                   True,
        "issuer":               doc.get("issuer"),
        "authorization_endpoint": doc.get("authorization_endpoint"),
        "token_endpoint":       doc.get("token_endpoint"),
        "userinfo_endpoint":    doc.get("userinfo_endpoint"),
    }


# ── Backups ───────────────────────────────────────────────────────────────────

@router.get("/backup/list")
def list_backups(_: models.User = Depends(require_admin)):
    """List available database backup files (admin only)."""
    if not _BACKUP_DIR.exists():
        return {"configured": False, "backups": []}
    files = sorted(
        [
            {
                "name": f.name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "created_ts": f.stat().st_mtime,
                "created": time.strftime(
                    "%Y-%m-%d %H:%M UTC", time.gmtime(f.stat().st_mtime)
                ),
            }
            for f in _BACKUP_DIR.glob("*.sql.gz")
        ],
        key=lambda x: x["created_ts"],
        reverse=True,
    )
    return {"configured": True, "backups": files}


@router.get("/backup/download/{filename}")
def download_backup(filename: str, _: models.User = Depends(require_admin)):
    """Stream a backup file to the browser (admin only)."""
    path = _BACKUP_DIR / filename
    try:
        resolved = path.resolve()
        if not str(resolved).startswith(str(_BACKUP_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return FileResponse(
        resolved,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{resolved.name}"'},
    )
