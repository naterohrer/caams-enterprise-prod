"""TOTP Multi-Factor Authentication endpoints."""

import os
from io import BytesIO

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import (
    create_access_token, create_refresh_token,
    decode_mfa_token,
    get_current_user, require_admin,
)
from app.database import get_db
from app.limiter import limiter
from app.logging_config import get_logger
from app.routers.audit_log import log_event

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])
log = get_logger("caams.mfa")

_ISSUER = os.environ.get("CAAMS_MFA_ISSUER", "CAAMS Enterprise")


def _gen_qr_svg(uri: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


@router.get("/setup", response_model=schemas.MFASetupResponse)
@limiter.limit("10/hour")
def mfa_setup(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate (or return existing) TOTP secret and QR code for the current user."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not current_user.totp_secret:
        current_user.totp_secret = pyotp.random_base32()
        db.commit()
    totp = pyotp.TOTP(current_user.totp_secret)
    uri = totp.provisioning_uri(name=current_user.username, issuer_name=_ISSUER)
    return schemas.MFASetupResponse(
        secret=current_user.totp_secret,
        otpauth_uri=uri,
        qr_svg=_gen_qr_svg(uri),
    )


@router.post("/confirm")
@limiter.limit("10/hour")
def mfa_confirm(
    request: Request,
    payload: schemas.MFAConfirm,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a TOTP code and enable MFA for the current user."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Call GET /auth/mfa/setup first")
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    current_user.mfa_enabled = True
    db.commit()
    log.info("MFA enabled | user=%s", current_user.username)
    log_event(db, user=current_user, action="MFA_ENABLED",
              resource_type="user", resource_id=str(current_user.id))
    return {"mfa_enabled": True}


@router.post("/disable")
@limiter.limit("10/hour")
def mfa_disable(
    request: Request,
    payload: schemas.MFADisable,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable MFA for the current user (requires current TOTP code)."""
    if not current_user.mfa_enabled or not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    current_user.mfa_enabled = False
    current_user.totp_secret = None
    db.commit()
    log.info("MFA disabled | user=%s", current_user.username)
    log_event(db, user=current_user, action="MFA_DISABLED",
              resource_type="user", resource_id=str(current_user.id))
    return {"mfa_enabled": False}


@router.delete("/admin/{user_id}")
def admin_reset_mfa(
    user_id: int,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: force-disable MFA for any user (no TOTP code required)."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.mfa_enabled = False
    user.totp_secret = None
    # Bump token version so existing sessions must re-authenticate with new MFA setup
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    log.info("MFA reset by admin | user=%s | admin=%s", user.username, admin.username)
    log_event(db, user=admin, action="MFA_ADMIN_RESET",
              resource_type="user", resource_id=str(user.id),
              details={"target_username": user.username})
    return {"mfa_enabled": False}


@router.post("/verify-login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def mfa_verify_login(
    request: Request,
    payload: schemas.MFAVerifyLogin,
    db: Session = Depends(get_db),
):
    """Complete MFA login: exchange mfa_token + TOTP code for a real JWT pair."""
    user_id = decode_mfa_token(payload.mfa_token)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="Invalid MFA session")
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    log.info("MFA login success | user=%s", user.username)
    log_event(db, user=user, action="MFA_LOGIN",
              resource_type="user", resource_id=str(user.id))
    tv = user.token_version or 0
    access = create_access_token({"sub": user.username, "role": user.role, "tv": tv})
    refresh = create_refresh_token({"sub": user.username, "role": user.role, "tv": tv})
    return schemas.TokenResponse(access_token=access, refresh_token=refresh, role=user.role)
